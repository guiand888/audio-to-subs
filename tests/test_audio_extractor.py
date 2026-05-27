"""Tests for audio_extractor module."""
import pytest
import subprocess
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

    @patch('src.audio_extractor.check_ffmpeg_available', return_value=True)
    def test_extract_audio_video_file_not_found(self, mock_check_ffmpeg, tmp_path):
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


class TestGetVideoDuration:
    """Test _get_video_duration function."""

    @patch('subprocess.run')
    def test_get_video_duration_success(self, mock_run):
        """Test getting video duration from valid file."""
        # Arrange
        mock_run.return_value = MagicMock(
            stdout='123.456\n',
            returncode=0
        )
        
        from src.audio_extractor import _get_video_duration
        
        # Act
        result = _get_video_duration("/path/to/video.mp4")
        
        # Assert
        assert result == 123.456
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert 'ffprobe' in call_args

    @patch('subprocess.run')
    def test_get_video_duration_subprocess_error(self, mock_run):
        """Test _get_video_duration handles subprocess errors."""
        # Arrange
        mock_run.side_effect = subprocess.CalledProcessError(1, 'ffprobe')
        
        from src.audio_extractor import _get_video_duration, AudioExtractionError
        
        # Act & Assert
        with pytest.raises(AudioExtractionError):
            _get_video_duration("/path/to/video.mp4")

    @patch('subprocess.run')
    def test_get_video_duration_invalid_output(self, mock_run):
        """Test _get_video_duration handles invalid output."""
        # Arrange
        mock_run.return_value = MagicMock(
            stdout='not_a_number\n',
            returncode=0
        )
        
        from src.audio_extractor import _get_video_duration, AudioExtractionError
        
        # Act & Assert
        with pytest.raises(AudioExtractionError):
            _get_video_duration("/path/to/video.mp4")


class TestAudioExtractionEdgeCases:
    """Test edge cases in audio extraction."""

    @patch('subprocess.Popen')
    @patch('subprocess.run')
    @patch('src.audio_extractor.check_ffmpeg_available')
    def test_extract_audio_with_progress_callback(self, mock_check_ffmpeg, mock_run, mock_popen, tmp_path):
        """Test extract_audio with progress callback."""
        # Arrange
        mock_check_ffmpeg.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        
        # Mock Popen for FFmpeg process
        mock_process = MagicMock()
        mock_process.communicate.return_value = ('', '')
        mock_process.returncode = 0
        mock_process.stdout = iter([])  # Empty progress output
        mock_popen.return_value = mock_process
        
        video_path = tmp_path / "test_video.mp4"
        video_path.touch()
        output_path = tmp_path / "output.wav"
        
        progress_messages = []
        def mock_callback(msg):
            progress_messages.append(msg)
        
        from src.audio_extractor import extract_audio
        
        # Act
        result = extract_audio(
            str(video_path), 
            str(output_path),
            progress_callback=mock_callback
        )
        
        # Assert
        assert result == str(output_path)
        # Progress callback should be called (even if no progress data)
        # The actual behavior depends on ffprobe availability

    @patch('subprocess.Popen')
    @patch('subprocess.run')
    @patch('src.audio_extractor.check_ffmpeg_available')
    @patch('src.audio_extractor._get_video_duration')
    def test_extract_audio_with_duration(self, mock_get_duration, mock_check_ffmpeg, mock_run, mock_popen, tmp_path):
        """Test extract_audio when duration is available for progress."""
        # Arrange
        mock_check_ffmpeg.return_value = True
        mock_get_duration.return_value = 100.0  # 100 second video
        mock_run.return_value = MagicMock(returncode=0)
        
        # Mock Popen for FFmpeg process with progress output
        # Note: stdout in subprocess.Popen is bytes, but _parse_ffmpeg_progress expects text
        # We need to mock it properly with text mode
        mock_process = MagicMock()
        # Create an iterator that yields text lines
        mock_process.stdout = iter([
            "out_time=00:00:50.0\n",  # 50 seconds
            "progress=end\n"
        ])
        mock_process.communicate.return_value = ('', '')
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        video_path = tmp_path / "test_video.mp4"
        video_path.touch()
        output_path = tmp_path / "output.wav"
        
        progress_messages = []
        def mock_callback(msg):
            progress_messages.append(msg)
        
        from src.audio_extractor import extract_audio
        
        # Act
        result = extract_audio(
            str(video_path), 
            str(output_path),
            progress_callback=mock_callback
        )
        
        # Assert
        assert result == str(output_path)
        # With duration available, progress should be reported

    @patch('subprocess.Popen')
    @patch('subprocess.run')
    @patch('src.audio_extractor.check_ffmpeg_available')
    @patch('src.audio_extractor._get_video_duration')
    def test_extract_audio_with_duration_error(self, mock_get_duration, mock_check_ffmpeg, mock_run, mock_popen, tmp_path):
        """Test extract_audio when _get_video_duration fails but we have progress callback."""
        from src.audio_extractor import AudioExtractionError
        # Arrange
        mock_check_ffmpeg.return_value = True
        mock_get_duration.side_effect = AudioExtractionError("ffprobe failed")
        mock_run.return_value = MagicMock(returncode=0)
        
        # Mock Popen for FFmpeg process
        mock_process = MagicMock()
        mock_process.communicate.return_value = ('', '')
        mock_process.returncode = 0
        mock_process.stdout = iter([])
        mock_popen.return_value = mock_process
        
        video_path = tmp_path / "test_video.mp4"
        video_path.touch()
        output_path = tmp_path / "output.wav"
        
        progress_messages = []
        def mock_callback(msg):
            progress_messages.append(msg)
        
        from src.audio_extractor import extract_audio, AudioExtractionError
        
        # Act - should not raise, should continue without progress
        result = extract_audio(
            str(video_path), 
            str(output_path),
            progress_callback=mock_callback
        )
        
        # Assert
        assert result == str(output_path)
        # Duration error should be caught and we continue without progress


class TestParseFFmpegProgress:
    """Test _parse_ffmpeg_progress function directly."""

    def test_parse_ffmpeg_progress_with_microseconds(self):
        """Test _parse_ffmpeg_progress handles microseconds pattern."""
        from src.audio_extractor import _parse_ffmpeg_progress
        
        progress_messages = []
        def mock_callback(msg):
            progress_messages.append(msg)
        
        # Simulate FFmpeg progress output with microseconds
        mock_stdout = iter([
            "out_time_us=50000000\n",  # 50 seconds in microseconds
            "progress=end\n"
        ])
        
        # Act
        _parse_ffmpeg_progress(
            mock_stdout,
            mock_callback,
            100.0,  # 100 second total duration
            "Extracting audio"
        )
        
        # Assert
        assert len(progress_messages) >= 1
        assert any("50.0" in msg for msg in progress_messages)

    def test_parse_ffmpeg_progress_with_timecode(self):
        """Test _parse_ffmpeg_progress handles timecode pattern."""
        from src.audio_extractor import _parse_ffmpeg_progress
        
        progress_messages = []
        def mock_callback(msg):
            progress_messages.append(msg)
        
        # Simulate FFmpeg progress output with timecode
        mock_stdout = iter([
            "out_time=00:00:50.5\n",  # 50.5 seconds
            "progress=end\n"
        ])
        
        # Act
        _parse_ffmpeg_progress(
            mock_stdout,
            mock_callback,
            100.0,  # 100 second total duration
            "Extracting audio"
        )
        
        # Assert
        assert len(progress_messages) >= 1
        assert any("50.5" in msg for msg in progress_messages)

    def test_parse_ffmpeg_progress_with_progress_end(self):
        """Test _parse_ffmpeg_progress handles progress=end marker."""
        from src.audio_extractor import _parse_ffmpeg_progress
        
        progress_messages = []
        def mock_callback(msg):
            progress_messages.append(msg)
        
        # Simulate FFmpeg progress output with just end marker
        mock_stdout = iter([
            "progress=end\n"
        ])
        
        # Act
        _parse_ffmpeg_progress(
            mock_stdout,
            mock_callback,
            100.0,
            "Extracting audio"
        )
        
        # Assert
        assert len(progress_messages) == 1
        assert "100.0%" in progress_messages[0]


class TestAudioExtractionSubprocessError:
    """Test subprocess error handling in audio extraction."""

    @patch('subprocess.Popen')
    @patch('subprocess.run')
    @patch('src.audio_extractor.check_ffmpeg_available')
    def test_extract_audio_subprocess_error(self, mock_check_ffmpeg, mock_run, mock_popen, tmp_path):
        """Test that extract_audio raises AudioExtractionError on subprocess error."""
        from src.audio_extractor import extract_audio, AudioExtractionError
        
        # Arrange
        mock_check_ffmpeg.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        
        # Mock failed Popen that raises SubprocessError
        mock_popen.side_effect = subprocess.SubprocessError("FFmpeg failed")
        
        video_path = tmp_path / "test_video.mp4"
        video_path.touch()
        output_path = tmp_path / "output.wav"
        
        # Act & Assert
        with pytest.raises(AudioExtractionError):
            extract_audio(str(video_path), str(output_path))
