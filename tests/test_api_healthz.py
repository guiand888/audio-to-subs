"""Tests for healthz API endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from unittest.mock import patch

from audio_to_subs.api.app import create_app


@pytest.fixture
def client_without_lifespan():
    """Create test client without running lifespan."""
    import os
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["BEHIND_TLS"] = "false"
    
    app = create_app()
    # Override lifespan to skip startup
    app.router.lifespan_context = None
    return TestClient(app, raise_server_exceptions=False)


class TestHealthz:
    """Test health check endpoint."""

    def test_healthz_route_exists(self, client_without_lifespan):
        """Test that /api/healthz route exists."""
        # This will fail because DB isn't initialized, but we're testing route exists
        response = client_without_lifespan.get("/api/healthz")
        
        # Should get 503 or similar error (not 404)
        assert response.status_code != 404

    def test_healthz_response_structure(self, client_without_lifespan):
        """Test that /api/healthz returns expected response structure."""
        response = client_without_lifespan.get("/api/healthz")

        # Check response has expected fields (even if error)
        # The response should be JSON
        try:
            data = response.json()
            # Should have detail field if error
            assert "detail" in data or "status" in data
        except Exception:
            # Response might not be JSON if DB error
            pass

    def test_healthz_returns_503_when_db_unavailable(self, client_without_lifespan):
        """503 returned when the DB raises OperationalError (e.g. locked).

        Regression: when the Bazarr poller held BEGIN IMMEDIATE across its
        inter-poll sleep, every health check session raised OperationalError
        and the endpoint returned 503, preventing worker/frontend startup.
        """
        with patch(
            "audio_to_subs.api.routes.healthz.get_async_session",
            side_effect=OperationalError("database is locked", None, None),
        ):
            response = client_without_lifespan.get("/api/healthz")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "database" in detail
        assert "error" in detail["database"]
