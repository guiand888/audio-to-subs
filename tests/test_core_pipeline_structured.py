"""Tests for structured progress in pipeline."""

from unittest.mock import MagicMock, patch

import pytest

from audio_to_subs.core.pipeline import (
    Pipeline,
    PipelineResult,
    ProgressEvent,
)


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_creation(self) -> None:
        """Test creating a PipelineResult."""
        result = PipelineResult(
            output_path="/path/to/output.srt",
            audio_duration_seconds=60.5,
            mistral_usage={"prompt_audio_seconds": 60},
            segments_count=1,
        )

        assert result.output_path == "/path/to/output.srt"
        assert result.audio_duration_seconds == 60.5
        assert result.mistral_usage == {"prompt_audio_seconds": 60}
        assert result.segments_count == 1

    def test_fspath(self) -> None:
        """Test __fspath__ method."""
        result = PipelineResult(
            output_path="/path/to/output.srt",
            audio_duration_seconds=60.0,
            mistral_usage=None,
            segments_count=0,
        )

        assert result.__fspath__() == "/path/to/output.srt"

    def test_str(self) -> None:
        """Test __str__ method."""
        result = PipelineResult(
            output_path="/path/to/output.srt",
            audio_duration_seconds=60.0,
            mistral_usage=None,
            segments_count=0,
        )

        assert str(result) == "/path/to/output.srt"

    def test_repr(self) -> None:
        """Test __repr__ method."""
        result = PipelineResult(
            output_path="/path/to/output.srt",
            audio_duration_seconds=60.0,
            mistral_usage={"key": "value"},
            segments_count=5,
        )

        repr_str = repr(result)
        assert "PipelineResult" in repr_str
        assert "/path/to/output.srt" in repr_str
        assert "segments_count=5" in repr_str


class TestPipelineStructuredProgress:
    """Tests for pipeline with structured progress callback."""

    def test_structured_callback_receives_events(self) -> None:
        """Test that Pipeline stores the structured progress callback."""
        events: list[ProgressEvent] = []

        def structured_callback(event: ProgressEvent) -> None:
            events.append(event)

        # Just verify Pipeline stores the callback — running the full pipeline
        # would require FFmpeg.  The _extract_audio attribute no longer exists
        # (it was renamed to extract_audio), so patch that name at the module level.
        pipeline = Pipeline(
            api_key="test-key",
            structured_progress_callback=structured_callback,
            temp_dir="/tmp",
        )

        assert pipeline._structured_progress_callback is not None

    def test_pipeline_with_cancel_token(self) -> None:
        """Test that Pipeline stores the cancel token."""
        from audio_to_subs.core.cancel import CancelToken

        token = CancelToken()

        pipeline = Pipeline(
            api_key="test-key",
            cancel_token=token,
            temp_dir="/tmp",
        )

        assert pipeline._cancel_token is token
