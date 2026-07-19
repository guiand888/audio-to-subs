"""Tests for queue_/claim.py module."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis

from audio_to_subs.queue_.claim import ClaimedJob, claim_one
from audio_to_subs.queue_.events import set_job_progress
from tests.conftest import make_job


class TestClaimedJob:
    """Tests for ClaimedJob dataclass."""

    def test_creation(self) -> None:
        """Test creating a ClaimedJob."""
        job_id = str(uuid4())
        claimed = ClaimedJob(
            id=job_id,
            media_path="/input/video.mp4",
            output_path="/output/video.srt",
            language_code="en",
            language_mode="explicit",
            output_format="srt",
            source="manual",
            source_ref=None,
        )

        assert claimed.id == job_id
        assert claimed.media_path == "/input/video.mp4"
        assert claimed.output_path == "/output/video.srt"
        assert claimed.language_code == "en"
        assert claimed.language_mode == "explicit"
        assert claimed.output_format == "srt"
        assert claimed.source == "manual"
        assert claimed.source_ref is None


class TestClaimOne:
    """Tests for claim_one function (async)."""

    async def test_claim_one_with_job(self, mock_session) -> None:
        """Test claiming a job when one is available."""
        job_id = str(uuid4())
        # execute() is awaited inside claim_one; use AsyncMock so that
        # `await session.execute(...)` returns a plain Mock with fetchone.
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (
            job_id,
            "/input/video.mp4",
            "/output/video.srt",
            "en",
            "explicit",
            "srt",
            "manual",
            None,
            False,  # overwrite (M6.g)
        )
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        result = await claim_one(mock_session, "worker-1")

        assert result is not None
        # claim_one returns the job id as a plain string matching Job.id's
        # String(36) column; passing a UUID to session.get(Job, ...) breaks
        # aiosqlite binding, so it must stay a str.
        assert isinstance(result.id, str)
        assert result.id == job_id
        assert result.media_path == "/input/video.mp4"
        assert result.language_mode == "explicit"
        assert mock_session.commit.called

    async def test_claim_one_no_job(self, mock_session) -> None:
        """Test claiming a job when none are available."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.rollback = AsyncMock()

        result = await claim_one(mock_session, "worker-1")

        assert result is None
        mock_session.rollback.assert_called_once()

    async def test_claim_one_error(self, mock_session) -> None:
        """Test claiming a job when an error occurs."""
        mock_session.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_session.rollback = AsyncMock()

        with pytest.raises(Exception, match="DB error"):
            await claim_one(mock_session, "worker-1")

        mock_session.rollback.assert_called_once()

    async def test_claim_one_clears_stale_redis_snapshot(
        self, mock_db_session
    ) -> None:
        """Claiming a job must drop any stale Redis progress snapshot so the
        live read path doesn't surface a previous run's progress for this id."""
        from audio_to_subs.db.models import JobStatus

        job = make_job(
            status=JobStatus.QUEUED,
            source="manual",
        )
        mock_db_session.add(job)
        await mock_db_session.commit()
        job_id = str(job.id)

        redis = FakeRedis()
        await set_job_progress(
            redis, job_id, percent=99, stage="extract", message="old run"
        )

        result = await claim_one(mock_db_session, "worker-1", redis=redis)
        assert result is not None
        assert result.id == job_id

        # Snapshot must be gone after claim.
        raw = await redis.hgetall(f"job:progress:{job_id}")
        assert raw == {}


@pytest.fixture
def mock_session():
    """Create a mock async session with AsyncMock for awaitable methods."""
    session = AsyncMock()
    return session
