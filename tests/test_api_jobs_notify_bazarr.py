"""Tests for the /api/jobs/{id}/notify-bazarr endpoint."""

import pytest
from uuid import uuid4

from audio_to_subs.db.models import Job, JobStatus, JobSource
from audio_to_subs.db.session import get_async_session


@pytest.mark.asyncio
async def test_notify_bazarr_job_not_found():
    """Test notify-bazarr returns 404 for non-existent job."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.jobs import router as jobs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(jobs_router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Non-existent job ID
        fake_job_id = uuid4()
        response = client.post(f"/api/jobs/{fake_job_id}/notify-bazarr")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_notify_bazarr_manual_job():
    """Test notify-bazarr for manual job returns skipped."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.jobs import router as jobs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(jobs_router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create a manual job
        job = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
        )
        session.add(job)
        await session.commit()

        response = client.post(f"/api/jobs/{job.id}/notify-bazarr")
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "skipped"
        assert "Manual job" in data["reason"]


@pytest.mark.asyncio
async def test_notify_bazarr_bazarr_movie_no_bazarr_config():
    """Test notify-bazarr for Bazarr movie without Bazarr config returns skipped."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.jobs import router as jobs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(jobs_router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create a Bazarr movie job
        job = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.BAZARR_MOVIE,
            source_ref="123",
            media_path="/test/video.mp4",
        )
        session.add(job)
        await session.commit()

        # Without Bazarr config, should return skipped
        response = client.post(f"/api/jobs/{job.id}/notify-bazarr")
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "skipped"
        assert "Bazarr not configured" in data["reason"]


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires actual Bazarr server to test")
async def test_notify_bazarr_bazarr_movie_with_config():
    """Test notify-bazarr for Bazarr movie with config triggers rescan.
    
    This test is skipped because it requires a real Bazarr server.
    In production, the endpoint should make a real HTTP POST to Bazarr.
    """
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.jobs import router as jobs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app
        from audio_to_subs.api.settings import Settings

        # This would require setting BAZARR_URL and BAZARR_API_KEY
        # For now, this test is skipped
        pass
