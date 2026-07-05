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
from typing import Generator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
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
    monkeypatch.setenv("ADMIN_PASSWORD", "test-secure-password-12345")
    monkeypatch.setenv("BEHIND_TLS", "false")

    # Reset module-level singletons so they re-read env on next access.
    _db_base._async_engines.clear()
    _db_base._sync_engine = None
    _api_settings._settings = None
    _auth_sessions._session_manager = None

    # Pre-create schema and default admin user synchronously so tests that
    # skip the lifespan (non-context-manager TestClient) still have a working DB.
    sync_url = f"sqlite:///{db_path}"
    # Import models BEFORE Base so that all tables are registered in
    # Base.metadata before create_all() is called.  Base alone has no tables.
    from audio_to_subs.db.models import User  # noqa: F401 — registers all models
    from audio_to_subs.db.base import Base
    from audio_to_subs.auth.passwords import hash_password

    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(sync_engine)
    with Session(sync_engine) as session:
        session.add(User(username="admin", password_hash=hash_password("test-secure-password-12345")))
        session.commit()
    sync_engine.dispose()

    yield

    # Cleanup: let the next test start completely fresh.
    _db_base._async_engines.clear()
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
async def mock_db_session():
    """Real async SQLAlchemy session backed by the per-test file DB.

    Used by tests that need async ORM operations (e.g. bazarr poller tests)
    without going through the full FastAPI stack.
    """
    from audio_to_subs.db.session import get_async_session
    from audio_to_subs.api.settings import get_settings

    settings = get_settings()
    async with get_async_session(settings.DATABASE_URL) as session:
        yield session


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
    db_base._async_engines.clear()
    api_settings._settings = None
    auth_sessions._session_manager = None

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def authenticated_client(api_client):
    """``api_client`` pre-authenticated as the seeded admin user.

    Every route except healthz/login requires auth (Phase 4.C3). Tests that
    exercise route behavior rather than the auth boundary itself should use
    this fixture instead of ``api_client`` so requests carry a valid session
    cookie.
    """
    response = api_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-secure-password-12345"},
    )
    assert response.status_code == 200, f"Fixture login failed: {response.text}"
    return api_client


def make_job(**kwargs):
    """Factory to create Job objects with sensible defaults for testing.

    Accepts any Job field as a kwarg override. Common fields:
      - status: JobStatus enum value
      - media_path: path string
      - source: JobSource enum value
      - language_code: ISO 639-1 code
      - audio_duration_seconds: float
      - estimated_cost_usd: float
    """
    from audio_to_subs.db.models import Job, JobStatus, JobSource

    defaults = {
        "id": str(uuid4()),
        "status": JobStatus.DONE,
        "source": JobSource.MANUAL,
        "media_path": "/test/video.mp4",
        "output_format": "srt",
    }
    defaults.update(kwargs)
    return Job(**defaults)


@pytest.fixture
def mocked_pipeline_deps():
    """Shared fixture for mocking all Pipeline dependencies.

    Patches 7 dependencies used in pipeline tests:
      - extract_audio
      - get_audio_duration
      - needs_splitting
      - split_audio
      - TranscriptionClient.transcribe_audio_with_timestamps
      - SubtitleGenerator.generate
      - Path (to avoid file existence checks)

    Returns a dict with all mocks under their function names.
    Yields to allow cleanup.
    """
    from audio_to_subs.core.transcription_client import TranscriptionClient

    with patch("audio_to_subs.core.pipeline.extract_audio") as mock_extract, \
         patch("audio_to_subs.core.pipeline.get_audio_duration", return_value=60.0) as mock_duration, \
         patch("audio_to_subs.core.pipeline.needs_splitting") as mock_needs_splitting, \
         patch("audio_to_subs.core.pipeline.split_audio") as mock_split, \
         patch.object(TranscriptionClient, "transcribe_audio_with_timestamps") as mock_transcribe, \
         patch("audio_to_subs.core.pipeline.SubtitleGenerator.generate") as mock_generate, \
         patch("audio_to_subs.core.pipeline.Path") as mock_path:

        # Configure defaults for common mocks
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_instance.stat.return_value.st_size = 1000000
        mock_path.return_value = mock_path_instance

        yield {
            "extract_audio": mock_extract,
            "get_audio_duration": mock_duration,
            "needs_splitting": mock_needs_splitting,
            "split_audio": mock_split,
            "transcribe_audio_with_timestamps": mock_transcribe,
            "generate": mock_generate,
            "path": mock_path,
        }
