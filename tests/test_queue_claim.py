"""Tests for queue_/claim.py module."""

from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from audio_to_subs.queue_.claim import claim_one, ClaimedJob


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
    """Tests for claim_one function."""

    @pytest.mark.asyncio
    async def test_claim_one_with_job(self, mock_session) -> None:
        """Test claiming a job when one is available."""
        from sqlalchemy import text
        
        # Mock session with a job
        job_id = str(uuid4())
        mock_session.execute = MagicMock(return_value=Mock(
            fetchone=Mock(return_value=(
                job_id,
                "/input/video.mp4",
                "/output/video.srt",
                "en",
                "srt",
                "manual",
                None,
            ))
        ))
        mock_session.commit = MagicMock()
        
        result = claim_one(mock_session, "worker-1")
        
        assert result is not None
        assert result.id == uuid4()  # UUID constructed from string
        assert result.media_path == "/input/video.mp4"
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_claim_one_no_job(self, mock_session) -> None:
        """Test claiming a job when none are available."""
        mock_session.execute = MagicMock(return_value=Mock(fetchone=Mock(return_value=None)))
        mock_session.rollback = MagicMock()
        
        result = claim_one(mock_session, "worker-1")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_claim_one_error(self, mock_session) -> None:
        """Test claiming a job when an error occurs."""
        mock_session.execute = MagicMock(side_effect=Exception("DB error"))
        mock_session.rollback = MagicMock()
        
        with pytest.raises(Exception):
            claim_one(mock_session, "worker-1")


@pytest.fixture
def mock_session():
    """Create a mock async session."""
    session = MagicMock()
    return session
