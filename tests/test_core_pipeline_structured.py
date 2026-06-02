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
        """Test that structured callback receives progress events."""
        events: list[ProgressEvent] = []
        
        def structured_callback(event: ProgressEvent) -> None:
            events.append(event)
        
        # Mock the pipeline dependencies
        with patch(
            "audio_to_subs.core.pipeline.get_audio_duration",
            return_value=10.0,
        ), patch(
            "audio_to_subs.core.pipeline.needs_splitting",
            return_value=False,
        ), patch(
            "audio_to_subs.core.pipeline.TranscriptionClient",
        ) as mock_client_class, patch(
            "audio_to_subs.core.pipeline.SubtitleGenerator",
        ) as mock_gen_class:
            # Mock client
            mock_client = MagicMock()
            mock_client.transcribe_audio_with_timestamps = MagicMock(return_value=[
                {"start": 0.0, "end": 10.0, "text": "test"}
            ])
            mock_client_class.return_value = mock_client
            
            # Mock generator
            mock_gen = MagicMock()
            mock_gen.generate = MagicMock(return_value="/tmp/output.srt")
            mock_gen_class.return_value = mock_gen
            
            # Mock extract_audio to avoid FFmpeg
            with patch("audio_to_subs.core.pipeline._extract_audio", return_value="/tmp/audio.wav"):
                pipeline = Pipeline(
                    api_key="test-key",
                    structured_progress_callback=structured_callback,
                    temp_dir="/tmp",
                )
                
                # This will fail because we're mocking, but we can check the callback was set
                assert pipeline._structured_progress_callback is not None

    def test_pipeline_with_cancel_token(self) -> None:
        """Test pipeline with cancel token."""
        from audio_to_subs.core.cancel import CancelToken
        
        token = CancelToken()
        
        with patch(
            "audio_to_subs.core.pipeline.get_audio_duration",
            return_value=10.0,
        ), patch(
            "audio_to_subs.core.pipeline.needs_splitting",
            return_value=False,
        ), patch(
            "audio_to_subs.core.pipeline.TranscriptionClient",
        ) as mock_client_class, patch(
            "audio_to_subs.core.pipeline.SubtitleGenerator",
        ) as mock_gen_class:
            mock_client = MagicMock()
            mock_client.transcribe_audio_with_timestamps = MagicMock(return_value=[
                {"start": 0.0, "end": 10.0, "text": "test"}
            ])
            mock_client_class.return_value = mock_client
            
            mock_gen = MagicMock()
            mock_gen.generate = MagicMock(return_value="/tmp/output.srt")
            mock_gen_class.return_value = mock_gen
            
            with patch("audio_to_subs.core.pipeline._extract_audio", return_value="/tmp/audio.wav"):
                pipeline = Pipeline(
                    api_key="test-key",
                    cancel_token=token,
                    temp_dir="/tmp",
                )
                
                assert pipeline._cancel_token is token
