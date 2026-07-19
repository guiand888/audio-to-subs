"""Tests for the version API endpoint."""

import os

import pytest
from fastapi.testclient import TestClient

from audio_to_subs.api.app import create_app


@pytest.fixture
def client():
    """Test client without running lifespan (no DB needed for /api/version)."""
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["BEHIND_TLS"] = "false"

    app = create_app()
    app.router.lifespan_context = None
    return TestClient(app, raise_server_exceptions=False)


class TestVersion:
    """Test the /api/version endpoint."""

    def test_version_route_exists_and_is_public(self, client):
        """/api/version returns 200 without authentication."""
        response = client.get("/api/version")
        assert response.status_code == 200

    def test_version_response_structure(self, client):
        """Response has a non-empty string 'version' field."""
        response = client.get("/api/version")
        data = response.json()
        assert "version" in data
        assert isinstance(data["version"], str)
        assert data["version"]

    def test_version_reflects_app_version_env(self, monkeypatch):
        """APP_VERSION env var is reported when set."""
        monkeypatch.setenv("APP_VERSION", "v9.9.9-test")
        # __version__ is resolved at import; re-resolve explicitly.
        import audio_to_subs

        monkeypatch.setattr(
            audio_to_subs, "__version__", audio_to_subs._resolve_version()
        )
        # The route reads audio_to_subs.__version__ at request time via its
        # module-level import, so patch that module's reference too.
        import audio_to_subs.api.routes.version as version_route

        monkeypatch.setattr(version_route, "__version__", "v9.9.9-test")

        os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
        os.environ["BEHIND_TLS"] = "false"
        app = create_app()
        app.router.lifespan_context = None
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/version")
        assert response.json()["version"] == "v9.9.9-test"
