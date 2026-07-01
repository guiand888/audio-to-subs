"""Tests for FastAPI app lifespan: startup/shutdown wiring.

Guards against the regression where podman compose down (SIGTERM → lifespan
shutdown) raised:
  AttributeError: 'State' object has no attribute 'shutdown'

Root cause: app.py never created app.state.shutdown before launching the
Bazarr poller, which expects the event to exist.

Note: the conftest _test_environment fixture pre-creates tables via
Base.metadata.create_all so tests don't need the full Alembic subprocess.
We mock subprocess.run to short-circuit the lifespan's Alembic call so that
both the conftest setup and the lifespan can target the same per-test DB.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from audio_to_subs.api.app import create_app


def _alembic_ok():
    """Fake subprocess.CompletedProcess simulating alembic upgrade head success."""
    return SimpleNamespace(returncode=0, stderr="", stdout="")


class TestLifespan:
    def test_lifespan_creates_shutdown_event(self):
        """The lifespan must create app.state.shutdown before the poller starts."""
        app = create_app()
        with patch("subprocess.run", return_value=_alembic_ok()):
            with TestClient(app, raise_server_exceptions=False):
                assert hasattr(app.state, "shutdown")
                assert isinstance(app.state.shutdown, asyncio.Event)

    def test_lifespan_shutdown_is_clean(self):
        """Exiting the lifespan context must not raise AttributeError or similar."""
        app = create_app()
        with patch("subprocess.run", return_value=_alembic_ok()):
            # If the context manager raises, the test fails.
            with TestClient(app, raise_server_exceptions=True):
                pass
