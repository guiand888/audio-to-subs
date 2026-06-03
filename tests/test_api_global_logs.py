"""Tests for the /api/logs global endpoint."""

import pytest
from datetime import datetime
from uuid import uuid4

from audio_to_subs.db.models import Job, JobLog, LogLevel
from audio_to_subs.db.session import get_async_session


@pytest.mark.asyncio
async def test_get_global_logs_empty():
    """Test /api/logs with no logs returns empty results."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.logs import global_logs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(global_logs_router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        response = client.get("/api/logs")
        assert response.status_code == 200
        data = response.json()
        assert data["logs"] == []
        assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_global_logs_with_entries():
    """Test /api/logs returns log entries."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.logs import global_logs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(global_logs_router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create test job
        job = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
        )
        session.add(job)
        await session.commit()

        # Create some log entries
        log1 = JobLog(
            job_id=job.id,
            ts=datetime.utcnow(),
            level=LogLevel.INFO,
            message="Job started",
        )
        log2 = JobLog(
            job_id=job.id,
            ts=datetime.utcnow(),
            level=LogLevel.WARNING,
            message="Low memory detected",
        )
        log3 = JobLog(
            job_id=None,
            ts=datetime.utcnow(),
            level=LogLevel.ERROR,
            message="Global system error",
        )

        session.add_all([log1, log2, log3])
        await session.commit()

        response = client.get("/api/logs")
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 3
        assert data["total"] == 3


@pytest.mark.asyncio
async def test_get_global_logs_filter_by_job_id():
    """Test /api/logs filters by job_id."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.logs import global_logs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(global_logs_router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create test jobs
        job1 = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video1.mp4",
        )
        job2 = Job(
            id=uuid4(),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video2.mp4",
        )
        session.add_all([job1, job2])
        await session.commit()

        # Create log entries for both jobs
        log1 = JobLog(
            job_id=job1.id,
            ts=datetime.utcnow(),
            level=LogLevel.INFO,
            message="Job 1 log",
        )
        log2 = JobLog(
            job_id=job2.id,
            ts=datetime.utcnow(),
            level=LogLevel.INFO,
            message="Job 2 log",
        )

        session.add_all([log1, log2])
        await session.commit()

        # Filter by job_id
        response = client.get(f"/api/logs?job_id={job1.id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 1
        assert data["logs"][0]["job_id"] == str(job1.id)


@pytest.mark.asyncio
async def test_get_global_logs_filter_by_level():
    """Test /api/logs filters by log level."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.logs import global_logs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(global_logs_router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create log entries with different levels
        log_info = JobLog(
            job_id=None,
            ts=datetime.utcnow(),
            level=LogLevel.INFO,
            message="Info message",
        )
        log_warning = JobLog(
            job_id=None,
            ts=datetime.utcnow(),
            level=LogLevel.WARNING,
            message="Warning message",
        )
        log_error = JobLog(
            job_id=None,
            ts=datetime.utcnow(),
            level=LogLevel.ERROR,
            message="Error message",
        )

        session.add_all([log_info, log_warning, log_error])
        await session.commit()

        # Filter by level
        response = client.get("/api/logs?level_filter=error")
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 1
        assert data["logs"][0]["level"] == "error"


@pytest.mark.asyncio
async def test_get_global_logs_pagination():
    """Test /api/logs pagination."""
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        from audio_to_subs.api.routes.logs import global_logs_router
        from fastapi.testclient import TestClient
        from audio_to_subs.api.app import create_app

        app = create_app()
        app.include_router(global_logs_router)
        client = TestClient(app)

        # Create tables
        from audio_to_subs.db.base import Base
        async with session.begin():
            await session.run_sync(Base.metadata.create_all)

        # Create 10 log entries
        logs = [
            JobLog(
                job_id=None,
                ts=datetime.utcnow(),
                level=LogLevel.INFO,
                message=f"Log message {i}",
            )
            for i in range(10)
        ]

        session.add_all(logs)
        await session.commit()

        # Test pagination
        response = client.get("/api/logs", params={"limit": 3, "offset": 0})
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 3
        assert data["total"] == 10

        response = client.get("/api/logs", params={"limit": 3, "offset": 3})
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 3

        response = client.get("/api/logs", params={"limit": 3, "offset": 9})
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 1
