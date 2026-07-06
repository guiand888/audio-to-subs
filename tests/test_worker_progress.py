"""Tests for the worker ProgressBridge (progress -> DB/Redis/log fan-out)."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from audio_to_subs.api.settings import get_settings
from audio_to_subs.core.cancel import CancelToken
from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus
from audio_to_subs.worker.progress import ProgressBridge


def make_bridge(job_id=None, redis=None, database_url=None) -> ProgressBridge:
    if job_id is None:
        job_id = uuid4()
    if redis is None:
        redis = AsyncMock()
    if database_url is None:
        settings = get_settings()
        database_url = settings.DATABASE_URL
    return ProgressBridge(
        database_url=database_url,
        redis=redis,
        job_id=job_id,
        token=CancelToken(),
        loop=asyncio.get_event_loop(),
    )


async def make_job_row(session, job_id) -> None:
    job = Job(
        id=str(job_id),
        status=JobStatus.RUNNING,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
        output_format="srt",
    )
    session.add(job)
    await session.flush()
    await session.commit()


class TestHandleProgressEvent:
    """Test ProgressBridge._handle's DB/Redis/log fan-out."""

    @pytest.mark.asyncio
    async def test_first_event_updates_db_and_publishes(self, mock_db_session):
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        redis = AsyncMock()
        bridge = make_bridge(job_id=job_id, redis=redis)

        await bridge._handle({"percent": 10, "stage": "extraction", "message": "Extracting"})

        redis.publish.assert_called()

        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == str(job_id)))
        ).scalar_one()
        assert refreshed.progress_percent == 10
        assert refreshed.progress_message == "Extracting"

    @pytest.mark.asyncio
    async def test_stage_transition_writes_job_log(self, mock_db_session):
        """A stage change must produce a job_logs row (regression: previously dead code)."""
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        bridge = make_bridge(job_id=job_id)

        await bridge._handle({"percent": 0, "stage": "extraction", "message": "Starting extraction"})
        await bridge._handle({"percent": 50, "stage": "transcription", "message": "Starting transcription"})

        logs = (
            await mock_db_session.execute(
                select(JobLog).where(JobLog.job_id == str(job_id))
            )
        ).scalars().all()

        stages_logged = [log.message for log in logs]
        assert any("transcription" in msg for msg in stages_logged)
        assert any("extraction" in msg for msg in stages_logged)

    @pytest.mark.asyncio
    async def test_same_stage_repeated_does_not_duplicate_log(self, mock_db_session):
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        bridge = make_bridge(job_id=job_id)

        await bridge._handle({"percent": 0, "stage": "extraction", "message": "start"})
        await bridge._handle({"percent": 5, "stage": "extraction", "message": "still going"})

        logs = (
            await mock_db_session.execute(
                select(JobLog).where(JobLog.job_id == str(job_id))
            )
        ).scalars().all()

        # Only the initial stage transition (None -> extraction) should log.
        assert len(logs) == 1

    @pytest.mark.asyncio
    async def test_handle_swallows_exceptions(self, mock_db_session):
        """_handle must never raise — progress reporting is best-effort."""
        job_id = uuid4()
        # Deliberately do not create the job row; redis is a broken mock that
        # raises to simulate a downstream failure.
        redis = AsyncMock()
        redis.publish.side_effect = Exception("redis down")
        bridge = make_bridge(job_id=job_id, redis=redis)

        # Should not raise despite redis failing.
        await bridge._handle({"percent": 10, "stage": "extraction", "message": "test"})

    @pytest.mark.asyncio
    async def test_job_log_job_id_stored_as_string(self, mock_db_session):
        """Regression: JobLog.job_id is String(36); passing a UUID object
        must not silently fail to write (previously swallowed by broad except).
        """
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        bridge = make_bridge(job_id=job_id)

        await bridge._write_job_log("extraction", "test message")

        logs = (
            await mock_db_session.execute(
                select(JobLog).where(JobLog.job_id == str(job_id))
            )
        ).scalars().all()
        assert len(logs) == 1
        assert logs[0].message == "[extraction] test message"


class TestConcurrentProgress:
    """Test concurrent progress updates don't corrupt data (D21 fix)."""

    @pytest.mark.asyncio
    async def test_concurrent_progress_updates_and_log_writes(self, mock_db_session):
        """Concurrent progress events should not corrupt the database.

        This tests that multiple concurrent _handle coroutines can safely
        update progress and write logs without AsyncSession concurrency issues.
        Each write uses its own session, serialized by _write_lock.
        """
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        redis = AsyncMock()
        bridge = make_bridge(job_id=job_id, redis=redis)

        # Simulate multiple concurrent progress events (like the pipeline
        # calling bridge.on_event multiple times quickly from a thread).
        # Each _handle call should:
        # 1. Publish to Redis
        # 2. Update progress in DB (with debouncing)
        # 3. Write log on stage transition
        events = [
            {"percent": 10, "stage": "extraction", "message": "Extracting audio"},
            {"percent": 20, "stage": "extraction", "message": "Still extracting"},
            {"percent": 50, "stage": "transcription", "message": "Transcribing"},
            {"percent": 75, "stage": "formatting", "message": "Formatting subtitles"},
            {"percent": 100, "stage": "done", "message": "Complete"},
        ]

        # Run all _handle calls concurrently
        await asyncio.gather(*[bridge._handle(event) for event in events])

        # Verify progress was updated to the final state
        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == str(job_id)))
        ).scalar_one()
        assert refreshed.progress_percent == 100
        assert "Complete" in refreshed.progress_message

        # Verify stage transitions were logged
        logs = (
            await mock_db_session.execute(
                select(JobLog).where(JobLog.job_id == str(job_id))
            )
        ).scalars().all()
        logged_stages = [log.message for log in logs]

        # All distinct stage transitions should be logged
        assert any("extraction" in msg for msg in logged_stages)
        assert any("transcription" in msg for msg in logged_stages)
        assert any("formatting" in msg for msg in logged_stages)
        assert any("done" in msg for msg in logged_stages)

    @pytest.mark.asyncio
    async def test_concurrent_writes_serialize_with_lock(self, mock_db_session):
        """Verify that concurrent writes are serialized by the write lock.

        This ensures that even with multiple concurrent _handle calls, the
        database writes don't interleave or cause conflicts.
        """
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        redis = AsyncMock()
        bridge = make_bridge(job_id=job_id, redis=redis)

        # Create many rapid stage transitions
        stages = ["extract", "transcribe", "format", "validate", "compress"]
        events = [
            {"percent": i * 20, "stage": stage, "message": f"Processing {stage}"}
            for i, stage in enumerate(stages)
        ]

        # Run concurrently
        await asyncio.gather(*[bridge._handle(event) for event in events])

        # All stage transitions should have been logged (no data loss)
        logs = (
            await mock_db_session.execute(
                select(JobLog).where(JobLog.job_id == str(job_id))
            )
        ).scalars().all()

        # Should have one log per distinct stage
        assert len(logs) == len(stages)
