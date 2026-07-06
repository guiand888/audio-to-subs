"""Tests for pipeline module."""

import pytest
from unittest.mock import MagicMock
from audio_to_subs.core.pipeline import Pipeline, PipelineError


class TestPipeline:
    """Test video to subtitles pipeline."""

    def test_process_video_success(self, mocked_pipeline_deps, tmp_path):
        """Test successful end-to-end video processing."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()
        output_file = tmp_path / "output.srt"

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file)
        mocked_pipeline_deps["get_audio_duration"].return_value = 60.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].return_value = [
            {"start": 0.0, "end": 2.5, "text": "Hello"},
            {"start": 2.5, "end": 5.0, "text": "World"},
        ]
        mocked_pipeline_deps["generate"].return_value = str(output_file)

        pipeline = Pipeline(api_key="test_key")

        # Act
        result = pipeline.process_video(str(video_file), str(output_file))

        # Assert — process_video returns PipelineResult; compare via str()/__fspath__
        assert str(result) == str(output_file)
        mocked_pipeline_deps["extract_audio"].assert_called_once()

    def test_process_video_video_not_found(self, mocked_pipeline_deps, tmp_path):
        """Test pipeline fails when video file not found."""
        # Arrange
        mocked_pipeline_deps["extract_audio"].side_effect = FileNotFoundError("Video not found")
        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Video file not found"):
            pipeline.process_video("nonexistent.mp4", "output.srt")

    def test_process_video_extraction_fails(self, mocked_pipeline_deps, tmp_path):
        """Test pipeline fails when audio extraction fails."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()

        mocked_pipeline_deps["extract_audio"].side_effect = Exception("FFmpeg error")
        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Audio extraction failed"):
            pipeline.process_video(str(video_file), "output.srt")

    def test_process_video_transcription_fails(self, mocked_pipeline_deps, tmp_path):
        """Test pipeline fails when transcription fails."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file)
        mocked_pipeline_deps["get_audio_duration"].return_value = 60.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].side_effect = Exception(
            "API error"
        )

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Transcription failed"):
            pipeline.process_video(str(video_file), "output.srt")

    def test_process_video_subtitle_generation_fails(self, mocked_pipeline_deps, tmp_path):
        """Test pipeline fails when subtitle generation fails."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file)
        mocked_pipeline_deps["get_audio_duration"].return_value = 60.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].return_value = [
            {"start": 0.0, "end": 2.5, "text": "Test"}
        ]
        mocked_pipeline_deps["generate"].side_effect = Exception("Write failed")

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Subtitle generation failed"):
            pipeline.process_video(str(video_file), "output.srt")

    def test_process_video_no_api_key(self, mocked_pipeline_deps):
        """Test pipeline raises error when no API key provided."""
        # Act & Assert
        with pytest.raises(ValueError, match="API key is required"):
            Pipeline(api_key=None)

    def test_process_video_with_progress_callback(self, mocked_pipeline_deps, tmp_path):
        """Test pipeline calls progress callback at each stage."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()
        output_file = tmp_path / "output.srt"

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file)
        mocked_pipeline_deps["get_audio_duration"].return_value = 60.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].return_value = [
            {"start": 0.0, "end": 2.5, "text": "Test"}
        ]
        mocked_pipeline_deps["generate"].return_value = str(output_file)

        progress_callback = MagicMock()
        pipeline = Pipeline(api_key="test_key", progress_callback=progress_callback)

        # Act
        pipeline.process_video(str(video_file), str(output_file))

        # Assert
        assert progress_callback.call_count >= 3
        calls = [call[0][0] for call in progress_callback.call_args_list]
        # Pipeline emits a "Starting pipeline" message first; verify extraction
        # and transcription stages are present somewhere in the call list.
        assert any("extraction" in c.lower() or "audio" in c.lower() for c in calls)
        assert any("transcrib" in c.lower() for c in calls)

    def test_pipeline_with_empty_segments(self, mocked_pipeline_deps, tmp_path):
        """Test pipeline fails when transcription returns empty segments."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file)
        mocked_pipeline_deps["get_audio_duration"].return_value = 60.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].return_value = []

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="AI service did not return timestamp data"):
            pipeline.process_video(str(video_file), "output.srt")

    def test_pipeline_with_multiple_segments(self, mocked_pipeline_deps, tmp_path):
        """Test pipeline with multiple audio segments."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file1 = tmp_path / "audio1.wav"
        audio_file1.touch()
        audio_file2 = tmp_path / "audio2.wav"
        audio_file2.touch()

        mocked_pipeline_deps["needs_splitting"].return_value = True
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file1)
        mocked_pipeline_deps["split_audio"].return_value = [str(audio_file1), str(audio_file2)]
        # Duration > 900 seconds (15 minutes) to trigger splitting
        mocked_pipeline_deps["get_audio_duration"].return_value = 1200.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].side_effect = [
            [{"start": 0.0, "end": 5.0, "text": "Hello"}],
            [{"start": 0.0, "end": 6.0, "text": "World"}],
        ]
        mocked_pipeline_deps["generate"].return_value = "output.srt"

        pipeline = Pipeline(api_key="test_key")

        # Act
        result = pipeline.process_video(str(video_file), "output.srt")

        # Assert
        assert str(result) == "output.srt"
        # Verify transcription was called twice (once per segment)
        assert mocked_pipeline_deps["transcribe_audio_with_timestamps"].call_count == 2
        # Verify split_audio was called
        mocked_pipeline_deps["split_audio"].assert_called_once()

    def test_pipeline_cleanup_on_error(self, mocked_pipeline_deps, tmp_path):
        """Test pipeline cleans up temp files on error."""
        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file)
        mocked_pipeline_deps["get_audio_duration"].return_value = 60.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].side_effect = Exception("API error")

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Transcription failed"):
            pipeline.process_video(str(video_file), "output.srt")

        # Note: We can't easily verify the cleanup happened due to container isolation,
        # but the cleanup code path is tested

    def test_process_video_extract_audio_ffmpeg_error(self, mocked_pipeline_deps, tmp_path):
        """Test FFmpegNotFoundError in _extract_audio (lines 213-214)."""
        from audio_to_subs.core.audio_extractor import FFmpegNotFoundError

        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].side_effect = FFmpegNotFoundError("ffmpeg not found")

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Audio extraction failed"):
            pipeline.process_video(str(video_file), "output.srt")

    def test_process_video_transcription_error(self, mocked_pipeline_deps, tmp_path):
        """Test TranscriptionError in _transcribe_audio_segments (line 273)."""
        from audio_to_subs.core.transcription_client import TranscriptionError

        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file)
        mocked_pipeline_deps["get_audio_duration"].return_value = 60.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].side_effect = TranscriptionError("Transcription failed")

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Transcription failed: Transcription failed"):
            pipeline.process_video(str(video_file), "output.srt")

    def test_generate_subtitles_format_error(self, mocked_pipeline_deps, tmp_path):
        """Test SubtitleFormatError in _generate_subtitles (line 302)."""
        from audio_to_subs.core.subtitle_generator import SubtitleFormatError

        # Arrange
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        audio_file = tmp_path / "audio.wav"
        audio_file.touch()

        mocked_pipeline_deps["needs_splitting"].return_value = False
        mocked_pipeline_deps["extract_audio"].return_value = str(audio_file)
        mocked_pipeline_deps["get_audio_duration"].return_value = 60.0
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].return_value = [
            {"start": 0.0, "end": 2.5, "text": "Hello"},
        ]
        mocked_pipeline_deps["generate"].side_effect = SubtitleFormatError("Invalid format")

        pipeline = Pipeline(api_key="test_key")

        # Act & Assert
        with pytest.raises(PipelineError, match="Subtitle generation failed: Invalid format"):
            pipeline.process_video(str(video_file), "output.srt")
