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


class TestAudioExtraction:
    """Test audio extraction from video files."""

    @patch('subprocess.Popen')
    @patch('subprocess.run')
    @patch('src.audio_extractor.check_ffmpeg_available')
    def test_extract_audio_success(self, mock_check_ffmpeg, mock_run, mock_popen, tmp_path):
        """Test successful audio extraction from video file."""
        # Arrange
        mock_check_ffmpeg.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        
        # Mock Popen for FFmpeg process
        mock_process = MagicMock()
        mock_process.communicate.return_value = ('', '')
        mock_process.returncode = 0
        mock_process.stdout = []
        mock_popen.return_value = mock_process
        
        video_path = tmp_path / "test_video.mp4"
        video_path.touch()
        output_path = tmp_path / "output.wav"
        
        from src.audio_extractor import extract_audio
        
        # Act
        result = extract_audio(str(video_path), str(output_path))
        
        # Assert
        assert result == str(output_path)
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == 'ffmpeg'
        assert str(video_path) in call_args
        assert str(output_path) in call_args

    @patch('src.audio_extractor.check_ffmpeg_available')
    def test_extract_audio_ffmpeg_not_available(self, mock_check_ffmpeg, tmp_path):
        """Test that extract_audio raises error when FFmpeg is not available."""
        # Arrange
        mock_check_ffmpeg.return_value = False
        video_path = tmp_path / "test_video.mp4"
        output_path = tmp_path / "output.wav"
        
        from src.audio_extractor import extract_audio, FFmpegNotFoundError
        
        # Act & Assert
        with pytest.raises(FFmpegNotFoundError):
            extract_audio(str(video_path), str(output_path))

    def test_extract_audio_video_file_not_found(self, tmp_path):
        """Test that extract_audio raises error when video file doesn't exist."""
        # Arrange
        video_path = tmp_path / "nonexistent.mp4"
        output_path = tmp_path / "output.wav"
        
        from src.audio_extractor import extract_audio
        
        # Act & Assert
        with pytest.raises(FileNotFoundError):
            extract_audio(str(video_path), str(output_path))

    @patch('subprocess.Popen')
    @patch('subprocess.run')
    @patch('src.audio_extractor.check_ffmpeg_available')
    def test_extract_audio_ffmpeg_command_fails(self, mock_check_ffmpeg, mock_run, mock_popen, tmp_path):
        """Test that extract_audio raises error when FFmpeg command fails."""
        # Arrange
        mock_check_ffmpeg.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        
        # Mock failed Popen
        mock_process = MagicMock()
        mock_process.communicate.return_value = ('', "Error processing video")
        mock_process.returncode = 1
        mock_popen.return_value = mock_process
        
        video_path = tmp_path / "test_video.mp4"
        video_path.touch()
        output_path = tmp_path / "output.wav"
        
        from src.audio_extractor import extract_audio, AudioExtractionError
        
        # Act & Assert
        with pytest.raises(AudioExtractionError):
            extract_audio(str(video_path), str(output_path))
