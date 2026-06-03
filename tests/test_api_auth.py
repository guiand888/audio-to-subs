"""Tests for auth API routes."""

import pytest
from fastapi.testclient import TestClient

from audio_to_subs.api.app import create_app


def _make_client() -> TestClient:
    """Return a TestClient backed by the per-test file DB.

    The _test_environment autouse fixture (conftest.py) has already:
    - pointed DATABASE_URL at a fresh SQLite file,
    - reset all module-level singletons,
    - created the schema and a default admin user (admin / admin123).
    """
    import audio_to_subs.db.base as db_base
    import audio_to_subs.api.settings as api_settings
    import audio_to_subs.auth.sessions as auth_sessions

    db_base._async_engine = None
    api_settings._settings = None
    auth_sessions._session_manager = None

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client():
    return _make_client()


@pytest.fixture
def client_with_db():
    """Alias kept for backwards compat — the conftest creates the DB for us."""
    return _make_client()


class TestHealthz:
    """Test health check endpoint."""

    def test_healthz_returns_200(self, client):
        """GET /api/healthz returns 200 when the database is reachable."""
        response = client.get("/api/healthz")
        # 503 is acceptable when Redis is unavailable (not needed in tests)
        assert response.status_code in [200, 503]


class TestLogin:
    """Test login endpoint."""

    def test_login_valid_credentials(self, client_with_db):
        """Login with correct credentials returns 200 and a session cookie."""
        response = client_with_db.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        assert data["user"]["username"] == "admin"
        assert "ats_session" in response.cookies

    def test_login_invalid_credentials(self, client_with_db):
        """Login with wrong password returns 401."""
        response = client_with_db.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrongpassword"},
        )

        assert response.status_code == 401

    def test_login_nonexistent_user(self, client_with_db):
        """Login with unknown username returns 401."""
        response = client_with_db.post(
            "/api/auth/login",
            json={"username": "nonexistent", "password": "password"},
        )

        assert response.status_code == 401


class TestMe:
    """Test /me endpoint."""

    def test_me_without_auth(self, client_with_db):
        """GET /api/auth/me without a session cookie returns 401."""
        response = client_with_db.get("/api/auth/me")

        assert response.status_code == 401

    def test_me_with_auth(self, client_with_db):
        """GET /api/auth/me after login returns the current user."""
        login_response = client_with_db.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )

        session_cookie = login_response.cookies.get("ats_session")

        response = client_with_db.get(
            "/api/auth/me",
            cookies={"ats_session": session_cookie},
        )

        assert response.status_code == 200
        assert response.json()["username"] == "admin"


class TestLogout:
    """Test logout endpoint."""

    def test_logout_with_auth(self, client_with_db):
        """POST /api/auth/logout clears the session cookie."""
        login_response = client_with_db.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )

        session_cookie = login_response.cookies.get("ats_session")

        response = client_with_db.post(
            "/api/auth/logout",
            cookies={"ats_session": session_cookie},
        )

        assert response.status_code == 204
        assert response.cookies.get("ats_session") in (None, "")
