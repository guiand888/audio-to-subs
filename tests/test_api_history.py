"""Tests for the /api/history endpoint."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from audio_to_subs.db.models import Job, JobStatus, JobSource
from audio_to_subs.db.session import get_async_session


@pytest.mark.asyncio
async def test_get_history_empty():
    """Test /api/history with no jobs returns empty results."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.history import router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        response = client.get("/api/history")
        assert response.status_code == 200
        data = response.json()
        assert data["jobs"] == []
        assert data["stats"]["total_jobs"] == 0
        assert data["stats"]["total_cost_usd"] == 0
        assert data["stats"]["total_duration_seconds"] == 0


@pytest.mark.asyncio
async def test_get_history_with_done_jobs():
    """Test /api/history returns done jobs with stats."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.history import router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create some done jobs
        job1 = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video1.mp4",
            audio_duration_seconds=120.5,
            estimated_cost_usd=0.50,
            language_code="en",
        )
        job2 = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.BAZARR_MOVIE,
            source_ref="123",
            media_path="/test/video2.mp4",
            audio_duration_seconds=180.0,
            estimated_cost_usd=0.75,
            language_code="fr",
        )

        session.add_all([job1, job2])
        await session.commit()

        response = client.get("/api/history")
        assert response.status_code == 200
        data = response.json()

        assert len(data["jobs"]) == 2
        assert data["stats"]["total_jobs"] == 2
        assert data["stats"]["total_cost_usd"] == pytest.approx(1.25, abs=0.001)
        assert data["stats"]["total_duration_seconds"] == pytest.approx(300.5, abs=0.01)
        assert data["stats"]["average_cost_usd"] == pytest.approx(0.625, abs=0.001)
        assert data["stats"]["count_by_status"]["done"] == 2
        assert data["stats"]["count_by_language"]["en"] == 1
        assert data["stats"]["count_by_language"]["fr"] == 1


@pytest.mark.asyncio
async def test_get_history_filters_by_status():
    """Test /api/history filters by status."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.history import router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create jobs with different statuses
        job_done = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video1.mp4",
        )
        job_failed = Job(
            id=uuid4(),
            status=JobStatus.FAILED,
            source=JobSource.MANUAL,
            media_path="/test/video2.mp4",
        )
        job_cancelled = Job(
            id=uuid4(),
            status=JobStatus.CANCELLED,
            source=JobSource.MANUAL,
            media_path="/test/video3.mp4",
        )

        session.add_all([job_done, job_failed, job_cancelled])
        await session.commit()

        # Test filtering by status
        response = client.get("/api/history", params={"status_filter": ["done"]})
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["status"] == "done"

        # Test multiple statuses
        response = client.get("/api/history", params={"status_filter": ["done", "failed"]})
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 2


@pytest.mark.asyncio
async def test_get_history_filters_by_source():
    """Test /api/history filters by source."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.history import router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create jobs with different sources
        job_bazarr = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.BAZARR_MOVIE,
            source_ref="123",
            media_path="/test/video1.mp4",
        )
        job_manual = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video2.mp4",
        )

        session.add_all([job_bazarr, job_manual])
        await session.commit()

        # Filter by source
        response = client.get("/api/history", params={"source_filter": "bazarr_movie"})
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["source"] == "bazarr_movie"


@pytest.mark.asyncio
async def test_get_history_pagination():
    """Test /api/history pagination."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.history import router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create 5 done jobs
        jobs = [
            Job(
                id=uuid4(),
                status=JobStatus.DONE,
                source=JobSource.MANUAL,
                media_path=f"/test/video{i}.mp4",
            )
            for i in range(5)
        ]

        session.add_all(jobs)
        await session.commit()

        # Test pagination
        response = client.get("/api/history", params={"limit": 2, "offset": 0})
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 2
        assert data["total"] == 5

        response = client.get("/api/history", params={"limit": 2, "offset": 2})
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 2

        response = client.get("/api/history", params={"limit": 2, "offset": 4})
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 1


@pytest.mark.asyncio
async def test_get_history_excludes_queued_and_running():
    """Test /api/history excludes queued and running jobs."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.history import router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create jobs with different statuses
        job_queued = Job(
            id=uuid4(),
            status=JobStatus.QUEUED,
            source=JobSource.MANUAL,
            media_path="/test/video1.mp4",
        )
        job_running = Job(
            id=uuid4(),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video2.mp4",
        )
        job_done = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video3.mp4",
        )

        session.add_all([job_queued, job_running, job_done])
        await session.commit()

        response = client.get("/api/history")
        assert response.status_code == 200
        data = response.json()

        # Should only return the done job
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["status"] == "done"
