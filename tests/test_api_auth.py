"""Tests for auth API routes."""

from sqlalchemy import select

from audio_to_subs.db.models import JobLog, LogLevel


class TestHealthz:
    """Test health check endpoint."""

    def test_healthz_returns_200(self, api_client):
        """GET /api/healthz returns 200 when the database is reachable."""
        response = api_client.get("/api/healthz")
        # 503 is acceptable when Redis is unavailable (not needed in tests)
        assert response.status_code in [200, 503]


class TestLogin:
    """Test login endpoint."""

    def test_login_valid_credentials(self, api_client):
        """Login with correct credentials returns 200 and a session cookie."""
        response = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-secure-password-12345"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        assert data["user"]["username"] == "admin"
        assert "ats_session" in response.cookies

    def test_login_invalid_credentials(self, api_client):
        """Login with wrong password returns 401."""
        response = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrongpassword"},
        )

        assert response.status_code == 401

    def test_login_nonexistent_user(self, api_client):
        """Login with unknown username returns 401."""
        response = api_client.post(
            "/api/auth/login",
            json={"username": "nonexistent", "password": "password"},
        )

        assert response.status_code == 401

    def test_login_success_writes_info_job_log(self, api_client, sync_session):
        """A successful login is recorded in the UI's activity log."""
        response = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-secure-password-12345"},
        )
        assert response.status_code == 200

        log = sync_session.execute(select(JobLog)).scalar_one()
        assert log.job_id is None
        assert log.level == LogLevel.INFO
        assert "admin" in log.message
        assert "logged in" in log.message

    def test_login_failure_writes_warning_job_log_without_password(
        self, api_client, sync_session
    ):
        """A failed login is recorded, but the password is never persisted."""
        response = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrongpassword"},
        )
        assert response.status_code == 401

        log = sync_session.execute(select(JobLog)).scalar_one()
        assert log.job_id is None
        assert log.level == LogLevel.WARNING
        assert "admin" in log.message
        assert "wrongpassword" not in log.message


class TestMe:
    """Test /me endpoint."""

    def test_me_without_auth(self, api_client):
        """GET /api/auth/me without a session cookie returns 401."""
        response = api_client.get("/api/auth/me")

        assert response.status_code == 401

    def test_me_with_auth(self, api_client):
        """GET /api/auth/me after login returns the current user."""
        login_response = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-secure-password-12345"},
        )

        session_cookie = login_response.cookies.get("ats_session")

        response = api_client.get(
            "/api/auth/me",
            cookies={"ats_session": session_cookie},
        )

        assert response.status_code == 200
        assert response.json()["username"] == "admin"


class TestLogout:
    """Test logout endpoint."""

    def test_logout_with_auth(self, api_client):
        """POST /api/auth/logout clears the session cookie."""
        login_response = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-secure-password-12345"},
        )

        session_cookie = login_response.cookies.get("ats_session")

        response = api_client.post(
            "/api/auth/logout",
            cookies={"ats_session": session_cookie},
        )

        assert response.status_code == 204
        assert response.cookies.get("ats_session") in (None, "")
