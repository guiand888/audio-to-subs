"""Tests for transcription_client module."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from mistralai.client.errors import SDKError

from audio_to_subs.core.transcription_client import (
    AudioFileError,
    TranscriptionClient,
    TranscriptionError,
)

MISTRAL_TRANSCRIPTIONS_URL = "https://api.mistral.ai/v1/audio/transcriptions"


def _write_audio_file(
    tmp_path, data: bytes = b"fake_audio_data", name: str = "test_audio.wav"
) -> str:
    """Write a small real file. Required because TranscriptionClient now streams
    the file via a live io.BufferedReader (not a fully-buffered bytes object,
    which is how the old code worked) — the Mistral SDK's File.content field
    only accepts bytes or a genuine io.BufferedReader/IO instance, and
    unittest.mock's mock_open() return value fails that validation, so tests
    need a real path on disk rather than a mocked builtins.open().
    """
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _sdk_error(status_code: int) -> SDKError:
    response = httpx.Response(status_code, request=httpx.Request("POST", "http://x"))
    return SDKError("API error occurred", response, "body")


def _mock_transcription_response() -> httpx.Response:
    """A minimal but schema-valid Mistral transcription response."""
    return httpx.Response(
        200,
        json={
            "model": "voxtral-mini-2602",
            "text": "hello world",
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
            "language": None,
        },
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

    def test_client_initialization_configures_split_timeouts(self):
        """Test read/write/connect/pool timeouts are set independently."""
        # Act
        client = TranscriptionClient(
            api_key="test_key",
            read_timeout=120.0,
            write_timeout=15.0,
            connect_timeout=5.0,
            pool_timeout=5.0,
        )

        # Assert
        assert client.timeout.read == 120.0
        assert client.timeout.write == 15.0
        assert client.timeout.connect == 5.0
        assert client.timeout.pool == 5.0

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_success(self, mock_mistral_class, tmp_path):
        """Test successful audio transcription."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "This is a test transcription."
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio(audio_path)

        # Assert
        assert result == "This is a test transcription."
        mock_client.audio.transcriptions.complete.assert_called_once()

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_file_not_found(self, mock_mistral_class):
        """Test transcription fails when audio file doesn't exist."""
        # Arrange
        client = TranscriptionClient(api_key="test_key")

        # Act & Assert
        with pytest.raises(AudioFileError, match="Audio file not found"):
            client.transcribe_audio("nonexistent.wav")

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_api_error(self, mock_mistral_class, tmp_path):
        """Test transcription handles non-retryable API errors."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client
        mock_client.audio.transcriptions.complete.side_effect = _sdk_error(400)

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act & Assert
        with pytest.raises(TranscriptionError, match="Transcription failed"):
            client.transcribe_audio(audio_path)
        # A permanent (4xx) error should not be retried
        assert mock_client.audio.transcriptions.complete.call_count == 1

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_with_timestamps(self, mock_mistral_class, tmp_path):
        """Test transcription with timestamp data."""
        # Arrange
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
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio_with_timestamps(audio_path)

        # Assert
        assert len(result) == 2
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.5
        assert result[0]["text"] == "Test"
        assert result[1]["start"] == 2.5
        assert result[1]["end"] == 5.0
        assert result[1]["text"] == "transcription"

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_with_language(self, mock_mistral_class, tmp_path):
        """Test transcription with language parameter."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Bonjour"
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key", language="fr")
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio(audio_path, language="en")

        # Assert
        assert result == "Bonjour"
        # Verify language was passed to API
        call_kwargs = mock_client.audio.transcriptions.complete.call_args[1]
        assert call_kwargs.get("language") == "en"

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_with_timestamps_and_progress(
        self, mock_mistral_class, tmp_path
    ):
        """Test transcription with timestamps and progress callback."""
        # Arrange
        progress_messages = []

        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))

        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Test"
        mock_response.segments = [
            MagicMock(start=0.0, end=2.5, text="Test"),
        ]
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(
            api_key="test_key", progress_callback=mock_progress_callback
        )
        audio_path = _write_audio_file(tmp_path, data=b"x" * 2048)

        # Act
        result = client.transcribe_audio_with_timestamps(
            audio_path, segment_number=1, total_segments=2
        )

        # Assert
        assert len(result) == 1
        assert result[0]["text"] == "Test"
        # Verify progress was called with segment info
        upload_messages = [msg for msg in progress_messages if "Uploading" in msg[0]]
        assert len(upload_messages) > 0
        # Check that at least one message has segment info
        assert any("1/2" in msg[0] for msg in upload_messages)
        # The explicit 0% fires unconditionally before the call. Real,
        # >0% progress requires httpx to actually consume the file while
        # sending the request, which doesn't happen here since `Mistral`
        # (hence `complete()`) is fully mocked -- that path is covered by
        # TestTranscriptionClientRealSDK.test_streaming_upload_reconstructs_full_file_body
        # instead, against the real multipart-encoding path.
        percentages = [msg[1] for msg in upload_messages if msg[1] is not None]
        assert 0 in percentages
        # A distinct "waiting for transcription" signal covers the read-phase
        # wait, which has no % of its own to report.
        assert any("waiting for transcription" in msg[0] for msg in progress_messages)

    def test_transcribe_audio_with_timestamps_file_not_found(self):
        """Test transcription with timestamps fails when file not found."""
        # Arrange
        client = TranscriptionClient(api_key="test_key")

        # Act & Assert
        with pytest.raises(AudioFileError, match="Audio file not found"):
            client.transcribe_audio_with_timestamps("nonexistent.wav")

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_with_timestamps_api_error(
        self, mock_mistral_class, tmp_path
    ):
        """Test transcription with timestamps handles non-retryable API errors."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client
        mock_client.audio.transcriptions.complete.side_effect = _sdk_error(422)

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act & Assert
        with pytest.raises(TranscriptionError, match="Transcription failed"):
            client.transcribe_audio_with_timestamps(audio_path)
        assert mock_client.audio.transcriptions.complete.call_count == 1

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_with_timestamps_no_segments(
        self, mock_mistral_class, tmp_path
    ):
        """Test transcription with timestamps when response has no segments."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        # Use a plain object without segments attribute
        class MockResponse:
            def __init__(self):
                self.text = "Test without segments"

        mock_response = MockResponse()
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio_with_timestamps(audio_path)

        # Assert - should return empty list
        assert result == []

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_with_custom_read_timeout(
        self, mock_mistral_class, tmp_path
    ):
        """Test read_timeout configures the client's httpx.Timeout, not a per-call kwarg."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Test transcription"
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key", read_timeout=120.0)
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio(audio_path)

        # Assert
        assert result == "Test transcription"
        assert client.timeout.read == 120.0
        assert client.timeout.write == 30.0  # default, independent of read_timeout
        # No per-call timeout_ms anymore -- falls back to httpx.USE_CLIENT_DEFAULT,
        # i.e. the client's own configured httpx.Timeout.
        call_kwargs = mock_client.audio.transcriptions.complete.call_args[1]
        assert "timeout_ms" not in call_kwargs

    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_with_timestamps_custom_read_timeout(
        self, mock_mistral_class, tmp_path
    ):
        """Test read_timeout also applies on the timestamps call path."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.segments = []
        mock_client.audio.transcriptions.complete.return_value = mock_response

        client = TranscriptionClient(api_key="test_key", read_timeout=90.0)
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio_with_timestamps(audio_path)

        # Assert
        assert result == []
        assert client.timeout.read == 90.0
        call_kwargs = mock_client.audio.transcriptions.complete.call_args[1]
        assert "timeout_ms" not in call_kwargs

    @patch("tenacity.nap.time.sleep")
    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_retries_on_transient_failure(
        self, mock_mistral_class, mock_sleep, tmp_path
    ):
        """Test that transcription retries on transient (retryable) failures."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Successful transcription"

        # First two calls fail with a retryable network timeout, third succeeds
        mock_client.audio.transcriptions.complete.side_effect = [
            httpx.ReadTimeout("Request timeout"),
            httpx.ReadTimeout("Request timeout"),
            mock_response,
        ]

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio(audio_path)

        # Assert
        assert result == "Successful transcription"
        # Verify that complete() was called 3 times (2 failures + 1 success)
        assert mock_client.audio.transcriptions.complete.call_count == 3

    @patch("tenacity.nap.time.sleep")
    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_does_not_retry_permanent_failure(
        self, mock_mistral_class, mock_sleep, tmp_path
    ):
        """Test that a permanent (401) API error is not retried at all."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client
        mock_client.audio.transcriptions.complete.side_effect = _sdk_error(401)

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act & Assert
        with pytest.raises(TranscriptionError, match="Transcription failed"):
            client.transcribe_audio(audio_path)
        assert mock_client.audio.transcriptions.complete.call_count == 1
        mock_sleep.assert_not_called()

    @patch("tenacity.nap.time.sleep")
    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_exhausts_retries_on_persistent_failure(
        self, mock_mistral_class, mock_sleep, tmp_path
    ):
        """Test that transcription fails after exhausting retries."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        # All calls fail with a retryable error
        mock_client.audio.transcriptions.complete.side_effect = httpx.ReadTimeout(
            "Persistent timeout"
        )

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act & Assert
        with pytest.raises(TranscriptionError, match="Transcription failed"):
            client.transcribe_audio(audio_path)

        # Verify that retries were attempted (max 4 attempts)
        assert mock_client.audio.transcriptions.complete.call_count == 4

    @patch("tenacity.nap.time.sleep")
    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_with_timestamps_retries_on_transient_failure(
        self, mock_mistral_class, mock_sleep, tmp_path
    ):
        """Test that transcription with timestamps retries on transient failures."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.segments = [
            MagicMock(start=0.0, end=2.5, text="Test"),
        ]

        # First call fails with a retryable connection error, second succeeds
        mock_client.audio.transcriptions.complete.side_effect = [
            httpx.ConnectError("Connection failed"),
            mock_response,
        ]

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio_with_timestamps(audio_path)

        # Assert
        assert len(result) == 1
        assert result[0]["text"] == "Test"
        # Verify that complete() was called 2 times (1 failure + 1 success)
        assert mock_client.audio.transcriptions.complete.call_count == 2

    @patch("tenacity.nap.time.sleep")
    @patch("audio_to_subs.core.transcription_client.Mistral")
    def test_transcribe_audio_retries_on_server_error(
        self, mock_mistral_class, mock_sleep, tmp_path
    ):
        """Test that a 503 SDKError (server-side, transient) is retried."""
        # Arrange
        mock_client = MagicMock()
        mock_mistral_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Recovered"
        mock_client.audio.transcriptions.complete.side_effect = [
            _sdk_error(503),
            mock_response,
        ]

        client = TranscriptionClient(api_key="test_key")
        audio_path = _write_audio_file(tmp_path)

        # Act
        result = client.transcribe_audio(audio_path)

        # Assert
        assert result == "Recovered"
        assert mock_client.audio.transcriptions.complete.call_count == 2


class TestTranscriptionClientRealSDK:
    """Recorded (respx-intercepted) tests that exercise the real Mistral SDK.

    These drive the actual ``mistralai`` ``complete()`` call path (no MagicMock
    of the SDK) so we verify the kwargs serialize into a well-formed multipart
    request. They stand in for the "recorded/VCR Mistral call" acceptance step
    for M5.7. The remaining open question from the probe note — whether a
    ``language``-omitted request is wire-equivalent to an explicit
    ``language=None`` — was confirmed live on 2026-07-10: both return equivalent
    transcripts/usage, so passing ``UNSET`` (omit) when no language is set is
    safe.
    """

    def _write_tmp_wav(self, tmp_path) -> str:
        path = tmp_path / "clip.wav"
        path.write_bytes(b"RIFF....WAVEfakeaudio")
        return str(path)

    @respx.mock
    def test_language_is_sent_when_provided(self, tmp_path):
        """With language set, the multipart request carries a language field."""
        route = respx.post(MISTRAL_TRANSCRIPTIONS_URL).mock(
            return_value=_mock_transcription_response()
        )

        client = TranscriptionClient(api_key="dummy", language="fr")
        result = client.transcribe_audio(self._write_tmp_wav(tmp_path), language="en")

        assert result == "hello world"
        assert route.called
        request = route.calls.last.request
        assert b"language" in request.content

    @respx.mock
    def test_language_omitted_when_absent(self, tmp_path):
        """With no language, UNSET keeps the field out of the wire request."""
        route = respx.post(MISTRAL_TRANSCRIPTIONS_URL).mock(
            return_value=_mock_transcription_response()
        )

        client = TranscriptionClient(api_key="dummy")
        result = client.transcribe_audio(self._write_tmp_wav(tmp_path))

        assert result == "hello world"
        assert route.called
        # The field must be absent (not serialized as null/empty) on the wire.
        assert b"\r\nlanguage\r\n" not in route.calls.last.request.content

    @respx.mock
    def test_timestamps_request_carries_granularity(self, tmp_path):
        """The timestamps path sends timestamp_granularities=["segment"]."""
        route = respx.post(MISTRAL_TRANSCRIPTIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "model": "voxtral-mini-2602",
                    "text": "hello",
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                    "language": None,
                    "segments": [{"start": 0.0, "end": 1.0, "text": "hello"}],
                },
            )
        )

        client = TranscriptionClient(api_key="dummy")
        segments = client.transcribe_audio_with_timestamps(
            self._write_tmp_wav(tmp_path)
        )

        assert len(segments) == 1
        assert segments[0]["text"] == "hello"
        assert route.called
        assert b"timestamp_granularities" in route.calls.last.request.content

    @respx.mock
    def test_streaming_upload_reconstructs_full_file_body(self, tmp_path):
        """A file larger than httpx's 64KB multipart chunk streams intact."""
        route = respx.post(MISTRAL_TRANSCRIPTIONS_URL).mock(
            return_value=_mock_transcription_response()
        )
        # Larger than httpx's FileField.CHUNK_SIZE (64KB) so this only passes
        # if multi-chunk streaming actually reconstructs the full body.
        original_bytes = bytes(range(256)) * 1000  # 256,000 bytes
        path = tmp_path / "large.wav"
        path.write_bytes(original_bytes)

        progress_calls: list[int] = []
        client = TranscriptionClient(
            api_key="dummy",
            progress_callback=lambda msg, pct: (
                progress_calls.append(pct) if pct is not None else None
            ),
        )
        result = client.transcribe_audio(str(path), segment_number=1, total_segments=1)

        assert result == "hello world"
        assert route.called
        assert original_bytes in route.calls.last.request.content
        # Real progress: more than just a 0/100 jump, and monotonically increasing.
        assert len(progress_calls) > 2
        assert progress_calls == sorted(progress_calls)
        assert progress_calls[0] == 0
        assert progress_calls[-1] == 100

    @respx.mock
    def test_retry_reopens_file_after_failed_attempt(self, tmp_path):
        """A retried attempt resends the full, uncorrupted file (not truncated)."""
        original_bytes = bytes(range(256)) * 1000
        path = tmp_path / "large.wav"
        path.write_bytes(original_bytes)

        route = respx.post(MISTRAL_TRANSCRIPTIONS_URL).mock(
            side_effect=[
                httpx.ReadTimeout("boom"),
                _mock_transcription_response(),
            ]
        )

        client = TranscriptionClient(api_key="dummy")
        result = client.transcribe_audio(str(path))

        assert result == "hello world"
        assert route.call_count == 2
        # The successful (second) attempt's body must be the full, uncorrupted file.
        assert original_bytes in route.calls[-1].request.content
