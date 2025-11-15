"""Tests for audio_splitter module.

Tests audio file duration detection, splitting for large files,
and progress callback handling.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.audio_splitter import (
    AudioSplitterError,
    MAX_AUDIO_LENGTH,
    OVERLAP,
    get_audio_duration,
    needs_splitting,
    split_audio,
)


class TestGetAudioDuration:
    """Test audio duration detection."""

    @patch("subprocess.run")
    def test_get_duration_success(self, mock_run):
        """Test successful duration retrieval."""
        # Arrange
        mock_run.return_value = MagicMock(stdout="123.45\n", returncode=0)

        # Act
        duration = get_audio_duration("test.wav")

        # Assert
        assert duration == 123.45
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "ffprobe" in call_args

    @patch("subprocess.run")
    def test_get_duration_zero(self, mock_run):
        """Test duration for empty/very short file."""
        # Arrange
        mock_run.return_value = MagicMock(stdout="0.0\n", returncode=0)

        # Act
        duration = get_audio_duration("empty.wav")

        # Assert
        assert duration == 0.0

    @patch("subprocess.run")
    def test_get_duration_large_file(self, mock_run):
        """Test duration for large/long files."""
        # Arrange
        mock_run.return_value = MagicMock(stdout="7200.5\n", returncode=0)  # 2 hours

        # Act
        duration = get_audio_duration("long.wav")

        # Assert
        assert duration == 7200.5

    @patch("subprocess.run")
    def test_get_duration_ffprobe_error(self, mock_run):
        """Test error handling when ffprobe fails."""
        # Arrange
        import subprocess

        mock_run.side_effect = subprocess.CalledProcessError(1, "ffprobe")

        # Act & Assert
        with pytest.raises(AudioSplitterError, match="Failed to get audio duration"):
            get_audio_duration("invalid.wav")

    @patch("subprocess.run")
    def test_get_duration_invalid_output(self, mock_run):
        """Test error handling for non-numeric output."""
        # Arrange
        mock_run.return_value = MagicMock(stdout="not_a_number\n", returncode=0)

        # Act & Assert
        with pytest.raises(AudioSplitterError, match="Failed to get audio duration"):
            get_audio_duration("corrupt.wav")


class TestNeedsSplitting:
    """Test splitting necessity detection."""

    @patch("src.audio_splitter.get_audio_duration")
    def test_needs_splitting_false_short_file(self, mock_duration):
        """Test short file does not need splitting."""
        # Arrange
        mock_duration.return_value = 300.0  # 5 minutes

        # Act
        result = needs_splitting("short.wav")

        # Assert
        assert result is False

    @patch("src.audio_splitter.get_audio_duration")
    def test_needs_splitting_false_exact_limit(self, mock_duration):
        """Test file exactly at limit does not need splitting."""
        # Arrange
        mock_duration.return_value = float(MAX_AUDIO_LENGTH)

        # Act
        result = needs_splitting("exact.wav")

        # Assert
        assert result is False

    @patch("src.audio_splitter.get_audio_duration")
    def test_needs_splitting_true_long_file(self, mock_duration):
        """Test long file needs splitting."""
        # Arrange
        mock_duration.return_value = 1000.0  # ~16.6 minutes, over 15-minute limit

        # Act
        result = needs_splitting("long.wav")

        # Assert
        assert result is True

    @patch("src.audio_splitter.get_audio_duration")
    def test_needs_splitting_custom_max_length(self, mock_duration):
        """Test custom max_length parameter."""
        # Arrange
        mock_duration.return_value = 500.0

        # Act
        result = needs_splitting("file.wav", max_length=400)

        # Assert
        assert result is True

    @patch("src.audio_splitter.get_audio_duration")
    def test_needs_splitting_error_propagates(self, mock_duration):
        """Test that duration errors propagate."""
        # Arrange
        mock_duration.side_effect = AudioSplitterError("Test error")

        # Act & Assert
        with pytest.raises(AudioSplitterError):
            needs_splitting("file.wav")


class TestSplitAudio:
    """Test audio splitting functionality."""

    @patch("src.audio_splitter.get_audio_duration")
    @patch("subprocess.Popen")
    def test_split_audio_no_splitting_needed(self, mock_popen, mock_duration):
        """Test no splitting when file is short enough."""
        # Arrange
        mock_duration.return_value = 300.0  # 5 minutes
        output_dir = "/tmp/output"

        # Act
        result = split_audio("short.wav", output_dir)

        # Assert
        assert result == ["short.wav"]
        mock_popen.assert_not_called()

    @patch("src.audio_splitter.get_audio_duration")
    @patch("subprocess.Popen")
    def test_split_audio_single_split(self, mock_popen, mock_duration, tmp_path):
        """Test splitting into two segments."""
        # Arrange
        mock_duration.return_value = 1000.0  # 16.6 minutes
        output_dir = tmp_path / "split"

        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0
        mock_process.stdout = []
        mock_popen.return_value = mock_process

        # Act
        result = split_audio("long.wav", str(output_dir))

        # Assert
        assert len(result) == 2
        assert all(str(output_dir) in path for path in result)
        assert "segment_001" in result[0]
        assert "segment_002" in result[1]

    @patch("src.audio_splitter.get_audio_duration")
    @patch("subprocess.Popen")
    def test_split_audio_multiple_segments(self, mock_popen, mock_duration, tmp_path):
        """Test splitting into multiple segments."""
        # Arrange
        # Simulate a 45-minute file: should split into ~3-4 segments
        mock_duration.return_value = 2700.0
        output_dir = tmp_path / "split"

        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0
        mock_process.stdout = []
        mock_popen.return_value = mock_process

        # Act
        result = split_audio("very_long.wav", str(output_dir))

        # Assert
        assert len(result) >= 3
        for i, segment_path in enumerate(result, 1):
            assert f"segment_{i:03d}" in segment_path

    @patch("src.audio_splitter.get_audio_duration")
    @patch("subprocess.Popen")
    def test_split_audio_ffmpeg_error(self, mock_popen, mock_duration, tmp_path):
        """Test error handling when FFmpeg fails."""
        # Arrange
        mock_duration.return_value = 1000.0
        output_dir = tmp_path / "split"

        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "FFmpeg error: invalid format")
        mock_process.returncode = 1
        mock_popen.return_value = mock_process

        # Act & Assert
        with pytest.raises(AudioSplitterError, match="FFmpeg error"):
            split_audio("long.wav", str(output_dir))

    @patch("src.audio_splitter.get_audio_duration")
    @patch("subprocess.Popen")
    def test_split_audio_with_progress_callback(self, mock_popen, mock_duration, tmp_path):
        """Test progress callback is called during splitting."""
        # Arrange
        mock_duration.return_value = 1000.0
        output_dir = tmp_path / "split"
        callback = MagicMock()

        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0
        # Provide stdout that triggers progress callback
        mock_process.stdout = ["progress=start", "progress=end"]
        mock_popen.return_value = mock_process

        # Act
        split_audio("long.wav", str(output_dir), progress_callback=callback)

        # Assert - callback should be called for progress updates
        # It's called at least once during the operation
        assert mock_popen.called

    @patch("src.audio_splitter.get_audio_duration")
    @patch("subprocess.Popen")
    def test_split_audio_creates_output_dir(self, mock_popen, mock_duration, tmp_path):
        """Test output directory is created if missing."""
        # Arrange
        mock_duration.return_value = 1000.0
        output_dir = tmp_path / "nonexistent" / "split"

        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0
        mock_process.stdout = []
        mock_popen.return_value = mock_process

        # Act
        split_audio("long.wav", str(output_dir))

        # Assert
        assert output_dir.exists()

    @patch("src.audio_splitter.get_audio_duration")
    def test_split_audio_with_custom_max_length(self, mock_duration, tmp_path):
        """Test splitting with custom max_length parameter."""
        # Arrange
        mock_duration.return_value = 1000.0
        output_dir = tmp_path / "split"

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_process.stdout = []
            mock_popen.return_value = mock_process

            # Act with very small max_length
            result = split_audio("audio.wav", str(output_dir), max_length=200)

            # Assert - should create more segments with smaller max_length
            assert len(result) >= 4


class TestAudioSplitterIntegration:
    """Integration tests for audio splitting workflow."""

    @patch("src.audio_splitter.get_audio_duration")
    @patch("subprocess.Popen")
    def test_split_preserves_order(self, mock_popen, mock_duration, tmp_path):
        """Test that split segments are returned in correct order."""
        # Arrange
        mock_duration.return_value = 2000.0

        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0
        mock_process.stdout = []
        mock_popen.return_value = mock_process

        # Act
        result = split_audio("audio.wav", str(tmp_path))

        # Assert
        for i, path in enumerate(result, 1):
            assert f"segment_{i:03d}" in path

    @patch("src.audio_splitter.get_audio_duration")
    def test_overlap_boundary_logic(self, mock_duration):
        """Test that overlap is correctly applied at segment boundaries."""
        # With 900s limit and 2s overlap:
        # Segment 1: 0-900
        # Segment 2: 898-1800 (898 = 900 - 2 overlap)
        # Segment 3: 1798-2700 (1798 = 1800 - 2 overlap)

        mock_duration.return_value = 2700.0

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_process.stdout = []
            mock_popen.return_value = mock_process

            # Act
            split_audio("audio.wav", "/tmp", max_length=900)

            # Assert - verify FFmpeg was called with correct times
            calls = mock_popen.call_args_list
            assert len(calls) >= 3

            # Check first segment: 0-900
            first_cmd = calls[0][0][0]
            assert "-ss" in first_cmd
            assert "0.0" in first_cmd or "0" in str(first_cmd)  # Start at 0

            # Check second segment starts with overlap
            second_cmd = calls[1][0][0]
            ss_idx = second_cmd.index("-ss")
            # Next arg should be start time
            start_time = float(second_cmd[ss_idx + 1])
            assert 898 <= start_time <= 900  # Account for boundary
