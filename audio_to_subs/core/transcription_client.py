"""Transcription client for Mistral AI Voxtral Mini."""

import logging
import os
from pathlib import Path
from typing import Any

import tenacity
from mistralai.client import Mistral
from mistralai.client.models import File

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when transcription fails."""

    pass


class AudioFileError(Exception):
    """Raised when audio file is invalid or not found."""

    pass


class TranscriptionClient:
    """Client for transcribing audio using Mistral AI Voxtral Mini."""

    def __init__(
        self,
        api_key: str,
        model: str = "voxtral-mini-latest",
        language: str | None = None,
        progress_callback: Any | None = None,
    ):
        """Initialize transcription client.

        Args:
            api_key: Mistral AI API key
            model: Transcription model to use (default: voxtral-mini-latest per Mistral docs)
            language: Optional language code for transcription (e.g., 'en', 'fr'). Default: None (auto-detect)
            progress_callback: Optional callback for progress updates (receives progress messages)

        Raises:
            ValueError: If API key is not provided
        """
        if not api_key:
            raise ValueError("API key is required")

        self.api_key = api_key.strip()
        self.model = model
        self.language = language
        self.progress_callback = progress_callback
        self._last_usage: dict[str, Any] | None = None
        logger.debug(
            f"TranscriptionClient initialized: model={model}, language={language}"
        )
        self.client = Mistral(api_key=self.api_key)

    def _read_file_with_progress(
        self,
        audio_path: str,
        segment_number: int | None,
        total_segments: int | None,
    ) -> "File":
        """Read an audio file into a Mistral File object.

        Note: The Mistral API requires the full file buffer, so streaming is not
        supported. This method reads the entire file into memory. Progress
        reporting (if enabled) shows 0% at start and 100% at completion.

        Args:
            audio_path: Path to audio file
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)

        Returns:
            Mistral File object wrapping the file's full contents
        """
        file_size = os.path.getsize(audio_path)
        report_progress = bool(
            self.progress_callback and segment_number and total_segments
        )

        if report_progress:
            mb_total = file_size / (1024 * 1024)
            self.progress_callback(
                f"Uploading segment {segment_number}/{total_segments}: 0 / {mb_total:.1f} MB (0%)",
                0,
            )

        with open(audio_path, "rb") as audio_file:
            file_content = audio_file.read()

        if report_progress:
            mb_total = file_size / (1024 * 1024)
            self.progress_callback(
                f"Uploading segment {segment_number}/{total_segments}: {mb_total:.1f} / {mb_total:.1f} MB (100%)",
                100,
            )

        return File(
            content=file_content,
            fileName=Path(audio_path).name,
            contentType="audio/wav",
        )

    def _capture_usage(self, response: Any) -> None:
        """Store Mistral response usage stats (for cost calculation), if present."""
        if hasattr(response, "usage"):
            usage_obj = response.usage
            if hasattr(usage_obj, "model_dump"):
                self._last_usage = usage_obj.model_dump()
            elif isinstance(usage_obj, dict):
                self._last_usage = usage_obj.copy()

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        retry=tenacity.retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def _call_mistral_transcription(
        self, model: str, file_obj: File, language: str | None, timeout: float = 60.0
    ) -> Any:
        """Call Mistral audio transcription API with retry and timeout.

        Args:
            model: Model name
            file_obj: File object
            language: Optional language code
            timeout: Request timeout in seconds (default: 60)

        Returns:
            Mistral transcription response

        Raises:
            Exception: On API error after all retries exhausted
        """
        kwargs = {"model": model, "file": file_obj, "timeout": timeout}
        if language:
            kwargs["language"] = language
        return self.client.audio.transcriptions.complete(**kwargs)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        retry=tenacity.retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def _call_mistral_transcription_with_timestamps(
        self, model: str, file_obj: File, timeout: float = 60.0
    ) -> Any:
        """Call Mistral audio transcription API with timestamps and retry.

        Args:
            model: Model name
            file_obj: File object
            timeout: Request timeout in seconds (default: 60)

        Returns:
            Mistral transcription response with segments

        Raises:
            Exception: On API error after all retries exhausted
        """
        kwargs = {
            "model": model,
            "file": file_obj,
            "timestamp_granularities": ["segment"],
            "timeout": timeout,
        }
        return self.client.audio.transcriptions.complete(**kwargs)

    def transcribe_audio(
        self,
        audio_path: str,
        language: str | None = None,
        segment_number: int | None = None,
        total_segments: int | None = None,
        timeout: float = 60.0,
    ) -> str:
        """Transcribe audio file to text with automatic retry on transient failures.

        Args:
            audio_path: Path to audio file
            language: Optional language code. Overrides instance default if provided.
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)
            timeout: Request timeout in seconds (default: 60)

        Returns:
            Transcribed text

        Raises:
            AudioFileError: If audio file not found
            TranscriptionError: If transcription fails after retries
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            logger.error(f"Audio file not found: {audio_path}")
            raise AudioFileError(f"Audio file not found: {audio_path}")

        try:
            logger.debug(f"Transcribing audio: {audio_path}")
            lang = language or self.language

            file_obj = self._read_file_with_progress(
                audio_path, segment_number, total_segments
            )

            logger.debug(
                f"Calling Mistral API: model={self.model}, language={lang}, timeout={timeout}s"
            )
            response = self._call_mistral_transcription(
                model=self.model,
                file_obj=file_obj,
                language=lang,
                timeout=timeout,
            )
            logger.debug(
                f"Transcription response received, text length: {len(response.text)}"
            )
            self._capture_usage(response)
            return response.text
        except Exception as e:
            logger.error(f"Transcription failed: {str(e)}")
            raise TranscriptionError(f"Transcription failed: {str(e)}") from e

    def transcribe_audio_with_timestamps(
        self,
        audio_path: str,
        language: str | None = None,
        segment_number: int | None = None,
        total_segments: int | None = None,
        timeout: float = 60.0,
    ) -> list[dict[str, Any]]:
        """Transcribe audio with timestamp information and automatic retry on transient failures.

        Args:
            audio_path: Path to audio file
            language: Optional language code. Overrides instance default if provided.
                Note: language is not compatible with timestamps per Mistral docs.
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)
            timeout: Request timeout in seconds (default: 60)

        Returns:
            List of segments with start, end times and text

        Raises:
            AudioFileError: If audio file not found
            TranscriptionError: If transcription fails after retries
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise AudioFileError(f"Audio file not found: {audio_path}")

        try:
            # Note: language parameter is intentionally ignored here.
            # Language and timestamp_granularities are mutually exclusive per Mistral docs.
            # Timestamps are required for subtitle generation, so language is disabled.
            # TODO: Support language parameter when Mistral API allows language + timestamps

            file_obj = self._read_file_with_progress(
                audio_path, segment_number, total_segments
            )

            logger.debug(f"Calling Mistral API with timestamps, timeout={timeout}s")
            response = self._call_mistral_transcription_with_timestamps(
                model=self.model,
                file_obj=file_obj,
                timeout=timeout,
            )
            logger.debug(f"Transcription response type: {type(response)}")
            self._capture_usage(response)

            segments = []
            if hasattr(response, "segments"):
                logger.debug(
                    f"Response has segments attribute with {len(response.segments)} segments"
                )
                for segment in response.segments:
                    segments.append(
                        {
                            "start": segment.start,
                            "end": segment.end,
                            "text": segment.text,
                        }
                    )
            else:
                logger.warning(
                    f"Response does not have 'segments' attribute. Response attributes: {vars(response) if hasattr(response, '__dict__') else 'no __dict__'}"
                )

            return segments
        except Exception as e:
            raise TranscriptionError(f"Transcription failed: {str(e)}") from e
