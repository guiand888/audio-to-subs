"""Tests for pipeline module."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.pipeline import Pipeline, PipelineError


class TestPipeline:
    """Test video to subtitles pipeline."""

    @patch("src.pipeline.needs_splitting")
    @patch("src.pipeline.SubtitleGenerator")
    @patch("src.pipeline.TranscriptionClient")
    @patch("src.pipeline.extract_audio")
    def test_process_video_success(
        self,
        mock_extract,
        mock_transcription_class,
        mock_generator_class,
        mock_needs_split,
        tmp_path,
    ):
        """Test successful end-to-end video processing."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()
        output_file = tmp_path / "output.srt"

        mock_needs_split.return_value = False
        mock_extract.return_value = str(audio_file)

        mock_transcription = MagicMock()
        mock_transcription_class.return_value = mock_transcription
        mock_transcription.transcribe_audio_with_timestamps.return_value = [
            {"start": 0.0, "end": 2.5, "text": "Hello"},
            {"start": 2.5, "end": 5.0, "text": "World"},
        ]

        mock_generator = MagicMock()
        mock_generator_class.return_value = mock_generator
        mock_generator.generate.return_value = str(output_file)

        pipeline = Pipeline(api_key="test_key")

        # Act
        result = pipeline.process_video(str(video_file), str(output_file))

        # Assert
        assert result == str(output_file)
        mock_extract.assert_called_once()
        mock_transcription.transcribe_audio_with_timestamps.assert_called_once()
        mock_generator.generate.assert_called_once()

    @patch("src.pipeline.extract_audio")
    def test_process_video_video_not_found(self, mock_extract, tmp_path):
        """Test pipeline fails when video file not found."""
        # Arrange
        mock_extract.side_effect = FileNotFoundError("Video not found")
        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Video file not found"):
            pipeline.process_video("nonexistent.mp4", "output.srt")

    @patch("src.pipeline.SubtitleGenerator")
    @patch("src.pipeline.TranscriptionClient")
    @patch("src.pipeline.extract_audio")
    def test_process_video_extraction_fails(
        self, mock_extract, mock_transcription_class, mock_generator_class, tmp_path
    ):
        """Test pipeline fails when audio extraction fails."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()

        mock_extract.side_effect = Exception("FFmpeg error")
        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Audio extraction failed"):
            pipeline.process_video(str(video_file), "output.srt")

    @patch("src.pipeline.needs_splitting")
    @patch("src.pipeline.SubtitleGenerator")
    @patch("src.pipeline.TranscriptionClient")
    @patch("src.pipeline.extract_audio")
    def test_process_video_transcription_fails(
        self,
        mock_extract,
        mock_transcription_class,
        mock_generator_class,
        mock_needs_split,
        tmp_path,
    ):
        """Test pipeline fails when transcription fails."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mock_needs_split.return_value = False
        mock_extract.return_value = str(audio_file)

        mock_transcription = MagicMock()
        mock_transcription_class.return_value = mock_transcription
        mock_transcription.transcribe_audio_with_timestamps.side_effect = Exception(
            "API error"
        )

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Transcription failed"):
            pipeline.process_video(str(video_file), "output.srt")

    @patch("src.pipeline.needs_splitting")
    @patch("src.pipeline.SubtitleGenerator")
    @patch("src.pipeline.TranscriptionClient")
    @patch("src.pipeline.extract_audio")
    def test_process_video_subtitle_generation_fails(
        self,
        mock_extract,
        mock_transcription_class,
        mock_generator_class,
        mock_needs_split,
        tmp_path,
    ):
        """Test pipeline fails when subtitle generation fails."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mock_needs_split.return_value = False
        mock_extract.return_value = str(audio_file)

        mock_transcription = MagicMock()
        mock_transcription_class.return_value = mock_transcription
        mock_transcription.transcribe_audio_with_timestamps.return_value = [
            {"start": 0.0, "end": 2.5, "text": "Test"}
        ]

        mock_generator = MagicMock()
        mock_generator_class.return_value = mock_generator
        mock_generator.generate.side_effect = Exception("Write failed")

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Subtitle generation failed"):
            pipeline.process_video(str(video_file), "output.srt")

    @patch("src.pipeline.SubtitleGenerator")
    @patch("src.pipeline.TranscriptionClient")
    @patch("src.pipeline.extract_audio")
    def test_process_video_no_api_key(
        self, mock_extract, mock_transcription_class, mock_generator_class
    ):
        """Test pipeline raises error when no API key provided."""
        # Act & Assert
        with pytest.raises(ValueError, match="API key is required"):
            Pipeline(api_key=None)

    @patch("src.pipeline.needs_splitting")
    @patch("src.pipeline.SubtitleGenerator")
    @patch("src.pipeline.TranscriptionClient")
    @patch("src.pipeline.extract_audio")
    def test_process_video_with_progress_callback(
        self,
        mock_extract,
        mock_transcription_class,
        mock_generator_class,
        mock_needs_split,
        tmp_path,
    ):
        """Test pipeline calls progress callback at each stage."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()
        output_file = tmp_path / "output.srt"

        mock_needs_split.return_value = False
        mock_extract.return_value = str(audio_file)

        mock_transcription = MagicMock()
        mock_transcription_class.return_value = mock_transcription
        mock_transcription.transcribe_audio_with_timestamps.return_value = [
            {"start": 0.0, "end": 2.5, "text": "Test"}
        ]

        mock_generator = MagicMock()
        mock_generator_class.return_value = mock_generator
        mock_generator.generate.return_value = str(output_file)

        progress_callback = MagicMock()
        pipeline = Pipeline(api_key="test_key", progress_callback=progress_callback)

        # Act
        pipeline.process_video(str(video_file), str(output_file))

        # Assert
        assert progress_callback.call_count >= 3
        calls = [call[0][0] for call in progress_callback.call_args_list]
        assert "extraction" in calls[0].lower() or "audio" in calls[0].lower()
        assert (
            "transcrib" in calls[1].lower()
        )  # Covers "transcribe", "transcription", etc.
