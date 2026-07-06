"""BDD feature test fixtures.

Provides respx mocking for Mistral API and other utilities for BDD scenarios.
Follows the pattern from tests/test_bazarr_client.py: mock only at the true
external boundary (HTTP API), not at internal class/function level.
"""

import json
import pytest
import httpx
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_mistral_api(respx_mock):
    """Mock the Mistral API HTTP endpoint for audio transcriptions.

    Returns a dict of convenience functions for setting up responses:
    - mock_success(segments): Returns a successful transcription response
    - mock_error(error_msg, status_code): Returns an error response

    Following the respx pattern from test_bazarr_client.py, this mocks the
    HTTP layer only — the real Mistral client code runs, but HTTP requests
    are intercepted and controlled.
    """

    def mock_success(segments=None):
        """Mock a successful Mistral transcription response."""
        if segments is None:
            segments = [
                {
                    "id": 0,
                    "seek": 0,
                    "start": 0.0,
                    "end": 2.5,
                    "text": "Hello world",
                    "avg_logprob": -0.1,
                    "compression_ratio": 1.2,
                    "no_speech_prob": 0.001,
                }
            ]

        response_body = {
            "id": "mock-id",
            "object": "list",
            "created": 1234567890,
            "model": "voxtral-mini-2602",
            "language": "en",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 100,
                "total_tokens": 110,
            },
            "text": " ".join(seg.get("text", "") for seg in segments),
            "segments": segments,
        }

        respx_mock.post(
            "https://api.mistral.ai/v1/files"
        ).mock(
            return_value=httpx.Response(200, json={"id": "mock-file-id", "filename": "test.wav"})
        )

        respx_mock.post(
            "https://api.mistral.ai/v1/audio/transcriptions"
        ).mock(
            return_value=httpx.Response(200, json=response_body)
        )

        return response_body

    def mock_error(error_msg="API Error", status_code=500):
        """Mock a Mistral API error response."""
        error_response = {
            "object": "error",
            "message": error_msg,
            "type": "api_error",
            "param": None,
            "code": status_code,
        }

        respx_mock.post(
            "https://api.mistral.ai/v1/audio/transcriptions"
        ).mock(
            return_value=httpx.Response(status_code, json=error_response)
        )

    return {
        "mock_success": mock_success,
        "mock_error": mock_error,
        "respx": respx_mock,
    }


@pytest.fixture
def mock_audio_extractor_minimal():
    """Mock extract_audio minimally: return a path without doing real extraction.

    This fixture can be used in specific scenarios where we want to avoid real
    FFmpeg calls. Simply request this fixture in a scenario to enable it.
    """
    def extract_audio_mock(video_path, output_path, progress_callback=None, cancel_token=None):
        # Create a minimal WAV file at the output path
        Path(output_path).touch()
        return str(output_path)

    with patch('audio_to_subs.core.pipeline.extract_audio', side_effect=extract_audio_mock):
        yield extract_audio_mock


@pytest.fixture(autouse=True)
def setup_bdd_environment():
    """Auto-setup for all BDD tests.

    Provides mocking of get_audio_duration and needs_splitting so tests
    don't need to probe real audio files. This keeps the boundary of
    mocking at the Mistral API level while letting extract_audio run for real
    (which allows us to test error handling on invalid files).
    """
    # Mock get_audio_duration to return a reasonable value
    # This is OK because we're not testing audio duration logic here
    with patch('audio_to_subs.core.pipeline.get_audio_duration', return_value=10.0):
        # Mock needs_splitting to return False (don't split audio)
        # This is OK because we're not testing splitting logic here
        with patch('audio_to_subs.core.pipeline.needs_splitting', return_value=False):
            yield
