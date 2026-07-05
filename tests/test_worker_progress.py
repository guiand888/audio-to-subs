"""Tests for the worker ProgressBridge (progress -> DB/Redis/log fan-out)."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from audio_to_subs.core.cancel import CancelToken
from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus
from audio_to_subs.worker.progress import ProgressBridge


def make_bridge(session, job_id=None, redis=None) -> ProgressBridge:
    if job_id is None:
        job_id = uuid4()
    if redis is None:
        redis = AsyncMock()
    return ProgressBridge(
        session=session,
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
        bridge = make_bridge(mock_db_session, job_id=job_id, redis=redis)

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
        bridge = make_bridge(mock_db_session, job_id=job_id)

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
        bridge = make_bridge(mock_db_session, job_id=job_id)

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
        bridge = make_bridge(mock_db_session, job_id=job_id, redis=redis)

        # Should not raise despite redis failing.
        await bridge._handle({"percent": 10, "stage": "extraction", "message": "test"})

    @pytest.mark.asyncio
    async def test_job_log_job_id_stored_as_string(self, mock_db_session):
        """Regression: JobLog.job_id is String(36); passing a UUID object
        must not silently fail to write (previously swallowed by broad except).
        """
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        bridge = make_bridge(mock_db_session, job_id=job_id)

        await bridge._write_job_log("extraction", "test message")

        logs = (
            await mock_db_session.execute(
                select(JobLog).where(JobLog.job_id == str(job_id))
            )
        ).scalars().all()
        assert len(logs) == 1
        assert logs[0].message == "[extraction] test message"
