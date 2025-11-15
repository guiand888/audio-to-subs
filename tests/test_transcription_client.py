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

    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_audio_success(self, mock_mistral_class, mock_file, mock_exists):
        """Test successful audio transcription."""
        # Arrange
        mock_exists.return_value = True
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

    @patch("src.transcription_client.Path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_audio_data")
    @patch("src.transcription_client.Mistral")
    def test_transcribe_with_timestamps(
        self, mock_mistral_class, mock_file, mock_exists
    ):
        """Test transcription with timestamp data."""
        # Arrange
        mock_exists.return_value = True
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
