"""Tests for audio_extractor module."""
import pytest
from unittest.mock import patch, MagicMock
from src.audio_extractor import check_ffmpeg_available


class TestFFmpegAvailability:
    """Test FFmpeg availability check."""

    @patch('subprocess.run')
    def test_check_ffmpeg_available_when_installed(self, mock_run):
        """Test that check_ffmpeg_available returns True when FFmpeg is installed."""
        # Arrange
        mock_run.return_value = MagicMock(returncode=0)
        
        # Act
        result = check_ffmpeg_available()
        
        # Assert
        assert result is True
        mock_run.assert_called_once_with(
            ['ffmpeg', '-version'],
            capture_output=True,
            check=False
        )

    @patch('subprocess.run')
    def test_check_ffmpeg_available_when_not_installed(self, mock_run):
        """Test that check_ffmpeg_available returns False when FFmpeg is not installed."""
        # Arrange
        mock_run.side_effect = FileNotFoundError()
        
        # Act
        result = check_ffmpeg_available()
        
        # Assert
        assert result is False

    @patch('subprocess.run')
    def test_check_ffmpeg_available_when_command_fails(self, mock_run):
        """Test that check_ffmpeg_available returns False when FFmpeg command fails."""
        # Arrange
        mock_run.return_value = MagicMock(returncode=1)
        
        # Act
        result = check_ffmpeg_available()
        
        # Assert
        assert result is False