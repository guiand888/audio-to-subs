"""Tests for GET /api/jobs/stream (global SSE) and /{job_id}/stream.

The global stream route was shadowed by the /{job_id} UUID route because
jobs_router was registered before stream_router in app.py.  The literal
path /api/jobs/stream was matched first, "stream" failed UUID validation,
and every client got 422 instead of text/event-stream.

Note on SSE testing: TestClient blocks until the response body is fully read,
so an infinite SSE stream causes tests to hang.  For tests that only care about
status and content-type (route wiring), EventSourceResponse is mocked with a
lightweight Response subclass that returns immediately.  Actual SSE mechanics
belong in integration / end-to-end tests against a real running server.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.responses import Response



def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class _FakeSSE(Response):
    """Stand-in for EventSourceResponse that returns immediately with the correct
    content-type header so the route handler can be tested without hanging."""

    def __init__(self, generator, **kwargs):
        super().__init__(content=b"", media_type="text/event-stream")


class TestGlobalStream:
    def test_global_stream_returns_200_event_stream(self, api_client):
        """GET /api/jobs/stream must return 200 text/event-stream, not 422.

        Patches EventSourceResponse with a lightweight stub so the route can be
        tested without hanging on an infinite SSE body.
        """
        with patch("audio_to_subs.api.routes.stream.EventSourceResponse", _FakeSSE):
            r = api_client.get("/api/jobs/stream")

        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]

    def test_jobs_list_still_reachable(self, api_client):
        """Regression: GET /api/jobs must still return 200 after route re-ordering."""
        r = api_client.get("/api/jobs")
        assert r.status_code == 200

    def test_job_by_uuid_still_reachable(self, api_client):
        """Regression: GET /api/jobs/{uuid} must still return 404 for unknown job."""
        r = api_client.get(f"/api/jobs/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_job_stream_by_uuid_returns_404_for_missing_job(self, api_client):
        """GET /api/jobs/{uuid}/stream for unknown job returns 404."""
        r = api_client.get(f"/api/jobs/{uuid.uuid4()}/stream")
        assert r.status_code == 404
