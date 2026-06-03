"""Shared pytest fixtures and test configuration.

Every test gets:
  - A fresh SQLite file in tmp_path (avoids in-memory cross-pool contamination).
  - All module-level singletons reset (engine, settings, session manager).
  - Minimal env vars so no test touches /data/* paths or external services.

Tests that exercise the full FastAPI stack (routes + DB) should use the
``api_client`` fixture, which creates the app and a ``TestClient`` backed by
the per-test file DB.  Tests that only need a raw SQLAlchemy session can use
``sync_session``.
"""

import os
from contextlib import asynccontextmanager
from typing import Generator
from unittest.mock import MagicMock, AsyncMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import audio_to_subs.db.base as _db_base
import audio_to_subs.api.settings as _api_settings
import audio_to_subs.auth.sessions as _auth_sessions

# Secret reused by every test — arbitrary but non-placeholder.
TEST_SESSION_SECRET = "test-only-session-secret-do-not-use-in-production"


@pytest.fixture(autouse=True)
def _test_environment(tmp_path, monkeypatch) -> Generator:
    """Reset all singletons and point everything at a per-test temp DB.

    Using a real SQLite file (not :memory:) lets alembic's subprocess, the
    async engine, and any sync helper sessions all share the same database
    without complex pool-sharing gymnastics.
    """
    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin123")
    monkeypatch.setenv("BEHIND_TLS", "false")

    # Reset module-level singletons so they re-read env on next access.
    _db_base._async_engine = None
    _db_base._sync_engine = None
    _api_settings._settings = None
    _auth_sessions._session_manager = None

    # Pre-create schema synchronously so tests that skip the lifespan still
    # have tables available.
    sync_url = f"sqlite:///{db_path}"
    from audio_to_subs.db.base import Base

    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    yield

    # Cleanup: let the next test start completely fresh.
    _db_base._async_engine = None
    _db_base._sync_engine = None
    _api_settings._settings = None
    _auth_sessions._session_manager = None


@pytest.fixture
def sync_session(tmp_path) -> Generator[Session, None, None]:
    """Sync SQLAlchemy session pointing at the test DB.

    Useful for inserting fixture data before making API requests with
    ``api_client``.  The session is committed and closed after the test.
    """
    from audio_to_subs.api.settings import get_settings

    settings = get_settings()
    sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite", "sqlite")
    engine = create_engine(sync_url, connect_args={"check_same_thread": False})
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def api_client():
    """FastAPI ``TestClient`` wired to the per-test SQLite file DB.

    The client is created with ``lifespan="on"`` (starlette default): the
    lifespan context manager runs, alembic migrates the file DB (idempotent,
    since ``_test_environment`` already created the schema), and bootstrap
    creates the ``admin`` user.  All routes therefore have a real DB.
    """
    from fastapi.testclient import TestClient
    from audio_to_subs.api.app import create_app
    import audio_to_subs.db.base as db_base
    import audio_to_subs.api.settings as api_settings
    import audio_to_subs.auth.sessions as auth_sessions

    # Reset again in case an earlier fixture call dirtied the cache.
    db_base._async_engine = None
    api_settings._settings = None
    auth_sessions._session_manager = None

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)
