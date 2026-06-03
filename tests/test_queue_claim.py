"""Tests for queue_/claim.py module."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from audio_to_subs.queue_.claim import ClaimedJob, claim_one


class TestClaimedJob:
    """Tests for ClaimedJob dataclass."""

    def test_creation(self) -> None:
        """Test creating a ClaimedJob."""
        job_id = uuid4()
        claimed = ClaimedJob(
            id=job_id,
            media_path="/input/video.mp4",
            output_path="/output/video.srt",
            language_code="en",
            output_format="srt",
            source="manual",
            source_ref=None,
        )

        assert claimed.id == job_id
        assert claimed.media_path == "/input/video.mp4"
        assert claimed.output_path == "/output/video.srt"
        assert claimed.language_code == "en"
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
            "srt",
            "manual",
            None,
        )
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        result = await claim_one(mock_session, "worker-1")

        assert result is not None
        # claim_one wraps the raw string from the DB in UUID()
        assert isinstance(result.id, UUID)
        assert str(result.id) == job_id
        assert result.media_path == "/input/video.mp4"
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


@pytest.fixture
def mock_session():
    """Create a mock async session with AsyncMock for awaitable methods."""
    session = AsyncMock()
    return session
