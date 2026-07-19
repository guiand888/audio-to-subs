"""Tests for the worker ProgressBridge (progress -> Redis/DB/log fan-out).

Phase 1: live progress is mirrored to a Redis hash (the authoritative live store)
rather than written to the DB on every event. The DB only receives terminal
progress via persist_result. These tests assert progress lands in the Redis
snapshot and that stage-transition logs are still written to the DB.
"""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select

from audio_to_subs.api.settings import get_settings
from audio_to_subs.core.cancel import CancelToken
from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus
from audio_to_subs.queue_.events import get_job_progress
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
    async def test_persists_stage_and_step_fields(self, mock_db_session):
        """M5.8 #4: progress_stage/step_index/step_total must land in Redis."""
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        redis = FakeRedis()
        bridge = make_bridge(job_id=job_id, redis=redis)

        await bridge._handle(
            {
                "percent": 42,
                "stage": "extract",
                "message": "Extracting",
                "step_index": 1,
                "step_total": 4,
            }
        )

        snapshot = await get_job_progress(redis, job_id)
        assert snapshot is not None
        assert snapshot["stage"] == "extract"
        assert snapshot["step_index"] == "1"
        assert snapshot["step_total"] == "4"
        assert snapshot["percent"] == "42"

    @pytest.mark.asyncio
    async def test_first_event_publishes_and_mirrors_to_redis(self, mock_db_session):
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        redis = FakeRedis()
        bridge = make_bridge(job_id=job_id, redis=redis)

        pubsub = redis.pubsub()
        await pubsub.subscribe(f"jobs:progress:{job_id}", "jobs:global")
        # Drain the subscription confirmation messages.
        await pubsub.get_message()
        await pubsub.get_message()

        await bridge._handle(
            {"percent": 10, "stage": "extraction", "message": "Extracting"}
        )

        msg = await pubsub.get_message()
        await pubsub.unsubscribe()
        assert msg is not None
        assert msg["type"] == "message"

        snapshot = await get_job_progress(redis, job_id)
        assert snapshot is not None
        assert snapshot["percent"] == "10"
        assert snapshot["message"] == "Extracting"

    @pytest.mark.asyncio
    async def test_stage_transition_writes_job_log(self, mock_db_session):
        """A stage change must produce a job_logs row (regression: previously dead code)."""
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        bridge = make_bridge(job_id=job_id)

        await bridge._handle(
            {"percent": 0, "stage": "extraction", "message": "Starting extraction"}
        )
        await bridge._handle(
            {
                "percent": 50,
                "stage": "transcription",
                "message": "Starting transcription",
            }
        )

        logs = (
            (
                await mock_db_session.execute(
                    select(JobLog).where(JobLog.job_id == str(job_id))
                )
            )
            .scalars()
            .all()
        )

        stages_logged = [log.message for log in logs]
        assert any("transcription" in msg for msg in stages_logged)
        assert any("extraction" in msg for msg in stages_logged)

    @pytest.mark.asyncio
    async def test_same_stage_repeated_does_not_duplicate_log(self, mock_db_session):
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        bridge = make_bridge(job_id=job_id)

        await bridge._handle({"percent": 0, "stage": "extraction", "message": "start"})
        await bridge._handle(
            {"percent": 5, "stage": "extraction", "message": "still going"}
        )

        logs = (
            (
                await mock_db_session.execute(
                    select(JobLog).where(JobLog.job_id == str(job_id))
                )
            )
            .scalars()
            .all()
        )

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
            (
                await mock_db_session.execute(
                    select(JobLog).where(JobLog.job_id == str(job_id))
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
        assert logs[0].message == "[extraction] test message"

    @pytest.mark.asyncio
    async def test_snapshot_write_is_debounced(self, mock_db_session, monkeypatch):
        """The Redis snapshot must be written immediately on percent/stage
        change but debounced (~1s) for repeated identical events, so a chatty
        pipeline can't flood Redis with no-op HSETs. The SSE pub/sub publish is
        always immediate and unaffected (verified separately)."""
        import audio_to_subs.worker.progress as progress_mod
        from audio_to_subs.queue_.events import set_job_progress as real_set

        calls = []

        async def spy_set(redis, job_id, percent, stage, message, step_index=None,
                          step_total=None):
            calls.append((percent, stage))
            await real_set(redis, job_id, percent, stage, message,
                           step_index=step_index, step_total=step_total)

        monkeypatch.setattr(progress_mod, "set_job_progress", spy_set)

        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        redis = FakeRedis()
        bridge = make_bridge(job_id=job_id, redis=redis)

        # Two identical events back-to-back: only the first should snapshot.
        await bridge._handle({"percent": 10, "stage": "extraction", "message": "a"})
        await bridge._handle({"percent": 10, "stage": "extraction", "message": "a"})

        # A percent change must force a new snapshot immediately.
        await bridge._handle({"percent": 55, "stage": "extraction", "message": "b"})

        assert calls == [(10, "extraction"), (55, "extraction")]

        snapshot = await get_job_progress(redis, job_id)
        assert snapshot is not None
        assert snapshot["percent"] == "55"


class TestConcurrentProgress:
    """Test concurrent progress updates don't corrupt data (D21 fix)."""

    @pytest.mark.asyncio
    async def test_concurrent_progress_updates_and_log_writes(self, mock_db_session):
        """Concurrent progress events should not corrupt the snapshot or DB.

        Multiple concurrent _handle coroutines must safely mirror the final
        progress into the Redis snapshot and write stage-transition logs
        without AsyncSession concurrency issues (each write uses its own
        session, serialized by _write_lock).
        """
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        redis = FakeRedis()
        bridge = make_bridge(job_id=job_id, redis=redis)

        # Simulate multiple concurrent progress events (like the pipeline
        # calling bridge.on_event multiple times quickly from a thread).
        events = [
            {"percent": 10, "stage": "extraction", "message": "Extracting audio"},
            {"percent": 20, "stage": "extraction", "message": "Still extracting"},
            {"percent": 50, "stage": "transcription", "message": "Transcribing"},
            {"percent": 75, "stage": "formatting", "message": "Formatting subtitles"},
            {"percent": 100, "stage": "done", "message": "Complete"},
        ]

        # Run all _handle calls concurrently
        await asyncio.gather(*[bridge._handle(event) for event in events])

        # Verify the Redis snapshot reflects the final state
        snapshot = await get_job_progress(redis, job_id)
        assert snapshot is not None
        assert snapshot["percent"] == "100"
        assert "Complete" in snapshot["message"]

        # Verify stage transitions were logged
        logs = (
            (
                await mock_db_session.execute(
                    select(JobLog).where(JobLog.job_id == str(job_id))
                )
            )
            .scalars()
            .all()
        )
        logged_stages = [log.message for log in logs]

        # All distinct stage transitions should be logged
        assert any("extraction" in msg for msg in logged_stages)
        assert any("transcription" in msg for msg in logged_stages)
        assert any("formatting" in msg for msg in logged_stages)
        assert any("done" in msg for msg in logged_stages)

    @pytest.mark.asyncio
    async def test_concurrent_writes_serialize_with_lock(self, mock_db_session):
        """Verify that concurrent writes are serialized by the write lock.

        Even with multiple concurrent _handle calls, all stage transitions
        must be logged (no data loss) and the Redis snapshot reflects the
        last event.
        """
        job_id = uuid4()
        await make_job_row(mock_db_session, job_id)
        redis = FakeRedis()
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
            (
                await mock_db_session.execute(
                    select(JobLog).where(JobLog.job_id == str(job_id))
                )
            )
            .scalars()
            .all()
        )

        # Should have one log per distinct stage
        assert len(logs) == len(stages)

        # Final snapshot reflects the last event
        snapshot = await get_job_progress(redis, job_id)
        assert snapshot is not None
        assert snapshot["percent"] == "80"
        assert snapshot["stage"] == "compress"
