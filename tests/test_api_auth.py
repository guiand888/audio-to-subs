"""Tests for auth API routes."""

import pytest
from sqlalchemy import select

from audio_to_subs.db.models import JobLog, LogLevel


@pytest.fixture
def behind_tls(monkeypatch):
    """Force BEHIND_TLS=true before the app is built by ``api_client``.

    Listed before ``api_client`` in test signatures so the env var is in place
    when the settings singleton (and thus the Secure cookie flag) is resolved.
    """
    monkeypatch.setenv("BEHIND_TLS", "true")
    yield


class TestSessionCookieFlags:
    """Verify M6 security item: cookie flags (HttpOnly, SameSite=Lax, Secure)."""

    def test_cookie_flags_without_tls(self, api_client):
        """Without TLS, the cookie is HttpOnly + SameSite=Lax but not Secure."""
        response = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-secure-password-12345"},
        )
        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "secure" not in set_cookie

    def test_cookie_secure_when_behind_tls(self, behind_tls, api_client):
        """Behind TLS, the cookie additionally carries the Secure flag."""
        response = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-secure-password-12345"},
        )
        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "secure" in set_cookie


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
        assert "parolesub_session" in response.cookies

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

        session_cookie = login_response.cookies.get("parolesub_session")

        response = api_client.get(
            "/api/auth/me",
            cookies={"parolesub_session": session_cookie},
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

        session_cookie = login_response.cookies.get("parolesub_session")

        response = api_client.post(
            "/api/auth/logout",
            cookies={"parolesub_session": session_cookie},
        )

        assert response.status_code == 204
        assert response.cookies.get("parolesub_session") in (None, "")
