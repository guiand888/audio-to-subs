"""Transcription client for Mistral AI Voxtral Mini."""

import logging
import os
from pathlib import Path
from typing import Any

from mistralai import Mistral
from mistralai.models import File

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

        self.api_key = api_key
        self.model = model
        self.language = language
        self.progress_callback = progress_callback
        logger.debug(f"TranscriptionClient initialized: model={model}, language={language}")
        self.client = Mistral(api_key=api_key)

    def transcribe_audio(
        self,
        audio_path: str,
        language: str | None = None,
        segment_number: int | None = None,
        total_segments: int | None = None,
    ) -> str:
        """Transcribe audio file to text.

        Args:
            audio_path: Path to audio file
            language: Optional language code. Overrides instance default if provided.
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)

        Returns:
            Transcribed text

        Raises:
            AudioFileError: If audio file not found
            TranscriptionError: If transcription fails
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            logger.error(f"Audio file not found: {audio_path}")
            raise AudioFileError(f"Audio file not found: {audio_path}")

        try:
            logger.debug(f"Transcribing audio: {audio_path}")
            lang = language or self.language
            file_size = os.path.getsize(audio_path)
            uploaded_bytes = 0
            chunk_size = 1024 * 1024  # 1MB chunks

            # Report upload start if progress tracking enabled
            if self.progress_callback and segment_number and total_segments:
                self.progress_callback(
                    f"Uploading segment {segment_number}/{total_segments}: 0 / {file_size / 1024 / 1024:.1f} MB (0%)",
                    0
                )

            with open(audio_path, "rb") as audio_file:
                file_content = b""
                while uploaded_bytes < file_size:
                    chunk = audio_file.read(min(chunk_size, file_size - uploaded_bytes))
                    if not chunk:
                        break
                    file_content += chunk
                    uploaded_bytes += len(chunk)

                    # Calculate and report progress
                    if self.progress_callback and segment_number and total_segments:
                        percentage = int((uploaded_bytes / file_size) * 100)
                        mb_uploaded = uploaded_bytes / (1024 * 1024)
                        mb_total = file_size / (1024 * 1024)
                        self.progress_callback(
                            f"Uploading segment {segment_number}/{total_segments}: {mb_uploaded:.1f}/{mb_total:.1f} MB ({percentage}%)",
                            percentage
                        )

                file_obj = File(
                    content=file_content,
                    fileName=Path(audio_path).name,
                    contentType="audio/wav",
                )

                # Report upload complete
                if self.progress_callback and segment_number and total_segments:
                    self.progress_callback(
                        f"Uploading segment {segment_number}/{total_segments}: {file_size / 1024 / 1024:.1f} / {file_size / 1024 / 1024:.1f} MB (100%)",
                        100
                    )

                kwargs = {"model": self.model, "file": file_obj}
                if lang:
                    kwargs["language"] = lang
                logger.debug(f"Calling Mistral API: model={self.model}, language={lang}")
                response = self.client.audio.transcriptions.complete(**kwargs)
                logger.debug(f"Transcription response received, text length: {len(response.text)}")
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
    ) -> list[dict[str, Any]]:
        """Transcribe audio with timestamp information.

        Args:
            audio_path: Path to audio file
            language: Optional language code. Overrides instance default if provided.
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)

        Returns:
            List of segments with start, end times and text

        Raises:
            AudioFileError: If audio file not found
            TranscriptionError: If transcription fails
            Note: timestamp_granularities is not compatible with language per Mistral docs
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise AudioFileError(f"Audio file not found: {audio_path}")

        try:
            lang = language or self.language
            file_size = os.path.getsize(audio_path)
            uploaded_bytes = 0
            chunk_size = 1024 * 1024  # 1MB chunks

            # Report upload start if progress tracking enabled
            if self.progress_callback and segment_number and total_segments:
                self.progress_callback(
                    f"Uploading segment {segment_number}/{total_segments}: 0 / {file_size / 1024 / 1024:.1f} MB (0%)",
                    0
                )

            with open(audio_path, "rb") as audio_file:
                file_content = b""
                while uploaded_bytes < file_size:
                    chunk = audio_file.read(min(chunk_size, file_size - uploaded_bytes))
                    if not chunk:
                        break
                    file_content += chunk
                    uploaded_bytes += len(chunk)

                    # Calculate and report progress
                    if self.progress_callback and segment_number and total_segments:
                        percentage = int((uploaded_bytes / file_size) * 100)
                        mb_uploaded = uploaded_bytes / (1024 * 1024)
                        mb_total = file_size / (1024 * 1024)
                        self.progress_callback(
                            f"Uploading segment {segment_number}/{total_segments}: {mb_uploaded:.1f}/{mb_total:.1f} MB ({percentage}%)",
                            percentage
                        )

                file_obj = File(
                    content=file_content,
                    fileName=Path(audio_path).name,
                    contentType="audio/wav",
                )

                # Report upload complete
                if self.progress_callback and segment_number and total_segments:
                    self.progress_callback(
                        f"Uploading segment {segment_number}/{total_segments}: {file_size / 1024 / 1024:.1f} / {file_size / 1024 / 1024:.1f} MB (100%)",
                        100
                    )

                kwargs = {
                    "model": self.model,
                    "file": file_obj,
                    "timestamp_granularities": ["segment"],
                }
                # Note: language and timestamp_granularities are mutually exclusive per Mistral docs
                # Timestamps are required for subtitle generation, so language is disabled for now.
                # TODO: Support language parameter when Mistral API allows language + timestamps
                # if lang:
                #     kwargs.pop("timestamp_granularities", None)
                #     kwargs["language"] = lang
                logger.debug(f"Calling Mistral API with timestamps: {kwargs.keys()}")
                response = self.client.audio.transcriptions.complete(**kwargs)
                logger.debug(f"Transcription response type: {type(response)}")
                logger.debug(f"Transcription response dir: {dir(response)}")
                logger.debug(f"Transcription response: {response}")

            segments = []
            if hasattr(response, "segments"):
                logger.debug(f"Response has segments attribute with {len(response.segments)} segments")
                for segment in response.segments:
                    segments.append(
                        {
                            "start": segment.start,
                            "end": segment.end,
                            "text": segment.text,
                        }
                    )
            else:
                logger.warning(f"Response does not have 'segments' attribute. Response attributes: {vars(response) if hasattr(response, '__dict__') else 'no __dict__'}")

            return segments
        except Exception as e:
            raise TranscriptionError(f"Transcription failed: {str(e)}") from e
