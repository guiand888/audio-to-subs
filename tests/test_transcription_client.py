"""Tests for transcription_client module."""

import pytest
from unittest.mock import patch, MagicMock, mock_open
from src.transcription_client import (
    TranscriptionClient,
    TranscriptionError,
    AudioFileError,
)


class TestTranscriptionClient:
    """Test Mistral AI transcription client."""

    def test_client_initialization_with_api_key(self):
        """Test client initializes with provided API key."""
        # Act
        client = TranscriptionClient(api_key="test_key_123")

        # Assert
        assert client.api_key == "test_key_123"

    def test_client_initialization_without_api_key(self):
        """Test client raises error when no API key provided."""
        # Act & Assert
        with pytest.raises(ValueError, match="API key is required"):
            TranscriptionClient(api_key=None)

    @patch("src.transcription_client.os.path.getsize")
    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_audio_success(self, mock_mistral_class, mock_file, mock_exists, mock_getsize):
        """Test successful audio transcription."""
        # Arrange
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "This is a test transcription."
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key")

        # Act
        result = client.transcribe_audio("test_audio.wav")

        # Assert
        assert result == "This is a test transcription."
        mock_client.audio.transcriptions.complete.assert_called_once()

    @patch("src.transcription_client.Mistral")
    def test_transcribe_audio_file_not_found(self, mock_mistral_class):
        """Test transcription fails when audio file doesn't exist."""
        # Arrange
        client = TranscriptionClient(api_key="test_key")

        # Act & Assert
        with pytest.raises(AudioFileError, match="Audio file not found"):
            client.transcribe_audio("nonexistent.wav")

    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_audio_api_error(
        self, mock_mistral_class, mock_file, mock_exists
    ):
        """Test transcription handles API errors."""
        # Arrange
        mock_exists.return_value = True
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client
        mock_client.audio.transcriptions.complete.side_effect = Exception("API Error")

        client = TranscriptionClient(api_key="test_key")

        # Act & Assert
        with pytest.raises(TranscriptionError, match="Transcription failed"):
            client.transcribe_audio("test_audio.wav")

    @patch("src.transcription_client.os.path.getsize")
    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_with_timestamps(
        self, mock_mistral_class, mock_file, mock_exists, mock_getsize
    ):
        """Test transcription with timestamp data."""
        # Arrange
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Test transcription"
        mock_response.segments = [
            MagicMock(start=0.0, end=2.5, text="Test"),
            MagicMock(start=2.5, end=5.0, text="transcription"),
        ]
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key")

        # Act
        result = client.transcribe_audio_with_timestamps("test_audio.wav")

        # Assert
        assert len(result) == 2
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.5
        assert result[0]["text"] == "Test"
        assert result[1]["start"] == 2.5
        assert result[1]["end"] == 5.0
        assert result[1]["text"] == "transcription"

    @patch("src.transcription_client.os.path.getsize")
    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_audio_with_language(self, mock_mistral_class, mock_file, mock_exists, mock_getsize):
        """Test transcription with language parameter."""
        # Arrange
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Bonjour"
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key", language="fr")

        # Act
        result = client.transcribe_audio("test_audio.wav", language="en")

        # Assert
        assert result == "Bonjour"
        # Verify language was passed to API
        call_kwargs = mock_client.audio.transcriptions.complete.call_args[1]
        assert call_kwargs.get("language") == "en"

    @patch("src.transcription_client.os.path.getsize")
    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_audio_with_timestamps_and_progress(
        self, mock_mistral_class, mock_file, mock_exists, mock_getsize
    ):
        """Test transcription with timestamps and progress callback."""
        # Arrange
        progress_messages = []

        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))

        mock_exists.return_value = True
        mock_getsize.return_value = 2048
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Test"
        mock_response.segments = [
            MagicMock(start=0.0, end=2.5, text="Test"),
        ]
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(
            api_key="test_key",
            progress_callback=mock_progress_callback
        )

        # Act
        result = client.transcribe_audio_with_timestamps(
            "test_audio.wav",
            segment_number=1,
            total_segments=2
        )

        # Assert
        assert len(result) == 1
        assert result[0]["text"] == "Test"
        # Verify progress was called with segment info
        upload_messages = [msg for msg in progress_messages if "Uploading" in msg[0]]
        assert len(upload_messages) > 0
        # Check that at least one message has segment info
        assert any("1/2" in msg[0] for msg in upload_messages)
        # Check that we have 0%, intermediate, and 100% progress
        percentages = [msg[1] for msg in upload_messages if msg[1] is not None]
        assert 0 in percentages
        assert 100 in percentages

    @patch("src.transcription_client.Path.exists")
    def test_transcribe_audio_with_timestamps_file_not_found(self, mock_exists):
        """Test transcription with timestamps fails when file not found."""
        # Arrange
        mock_exists.return_value = False
        client = TranscriptionClient(api_key="test_key")

        # Act & Assert
        with pytest.raises(AudioFileError, match="Audio file not found"):
            client.transcribe_audio_with_timestamps("nonexistent.wav")

    @patch("src.transcription_client.os.path.getsize")
    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_audio_with_timestamps_api_error(
        self, mock_mistral_class, mock_file, mock_exists, mock_getsize
    ):
        """Test transcription with timestamps handles API errors."""
        # Arrange
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client
        mock_client.audio.transcriptions.complete.side_effect = Exception("API Error")

        client = TranscriptionClient(api_key="test_key")

        # Act & Assert
        with pytest.raises(TranscriptionError, match="Transcription failed"):
            client.transcribe_audio_with_timestamps("test_audio.wav")

    @patch("src.transcription_client.os.path.getsize")
    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_audio_with_timestamps_no_segments(
        self, mock_mistral_class, mock_file, mock_exists, mock_getsize
    ):
        """Test transcription with timestamps when response has no segments."""
        # Arrange
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        # Use a plain object without segments attribute
        class MockResponse:
            def __init__(self):
                self.text = "Test without segments"
        
        mock_response = MockResponse()
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key")

        # Act
        result = client.transcribe_audio_with_timestamps("test_audio.wav")

        # Assert - should return empty list
        assert result == []
