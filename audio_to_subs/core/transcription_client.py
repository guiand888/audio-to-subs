"""Transcription client for Mistral AI Voxtral Mini."""

import io
import logging
import os
from pathlib import Path
from typing import Any, Callable

import httpx
import tenacity
from mistralai.client import Mistral
from mistralai.client.errors import SDKError
from mistralai.client.models import File, TimestampGranularity
from mistralai.client.types import UNSET

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when transcription fails."""

    pass


class AudioFileError(Exception):
    """Raised when audio file is invalid or not found."""

    pass


def _is_retryable_transcription_error(exc: BaseException) -> bool:
    """Decide whether a transcription failure is worth retrying.

    Network/transport-level failures (timeouts, connection errors) and
    server-side 429/5xx responses are transient — worth retrying. Client
    errors (400/401/403/404/422/...) are permanent: retrying can't fix a bad
    API key or a malformed request, it only delays the failure and adds load
    for no benefit.
    """
    if isinstance(
        exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)
    ):
        return True
    if isinstance(exc, SDKError):
        return (
            exc.raw_response.status_code == 429 or exc.raw_response.status_code >= 500
        )
    return False


class _ProgressTrackingReader(io.BufferedReader):
    """Wraps a raw file so httpx's chunked reads drive real upload progress.

    Must subclass ``io.BufferedReader`` itself — not just implement
    ``.read()``, and not a plain ``io.RawIOBase`` subclass. The Mistral SDK's
    ``File.content`` is a pydantic field typed
    ``Union[bytes, IO[bytes], io.BufferedReader]``, and only a genuine
    ``io.BufferedReader`` (or subclass) instance passes validation; verified
    directly that a plain wrapper class and an ``io.RawIOBase`` subclass are
    both rejected with the same error `mock_open` produces.

    httpx's multipart encoder (``httpx/_multipart.py``) calls ``.read(64KB)``
    in a loop on any file-like ``content`` — this is what turns those calls
    into real upload progress instead of a single eager read.
    """

    def __init__(
        self,
        raw: io.FileIO,
        total_size: int,
        on_progress: Callable[[int, int], None] | None,
    ):
        super().__init__(raw)
        self._total_size = total_size
        self._on_progress = on_progress
        self._bytes_read = 0
        self._last_reported_pct = -1

    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(size)
        self._bytes_read += len(chunk)
        if self._on_progress:
            pct = (
                int(100 * self._bytes_read / self._total_size)
                if self._total_size
                else 100
            )
            # Throttle to once per percentage point crossed, not once per
            # 64KB chunk (thousands of calls for a large file).
            if pct != self._last_reported_pct:
                self._last_reported_pct = pct
                self._on_progress(self._bytes_read, self._total_size)
        return chunk


class TranscriptionClient:
    """Client for transcribing audio using Mistral AI Voxtral Mini."""

    def __init__(
        self,
        api_key: str,
        model: str = "voxtral-mini-2602",
        language: str | None = None,
        progress_callback: Any | None = None,
        read_timeout: float = 60.0,
        write_timeout: float = 30.0,
        connect_timeout: float = 10.0,
        pool_timeout: float = 10.0,
    ):
        """Initialize transcription client.

        Args:
            api_key: Mistral AI API key
            model: Transcription model to use (default: voxtral-mini-2602)
            language: Optional language code for transcription (e.g., 'en', 'fr'). Default: None (auto-detect)
            progress_callback: Optional callback for progress updates (receives progress messages)
            read_timeout: Seconds to wait for Mistral to finish processing and
                respond. This is the one dimension that should scale with
                expected audio duration (see Pipeline._transcription_timeout).
            write_timeout: Seconds to wait per ~64KB upload chunk before
                treating the connection as stalled. Independent of file size
                or audio duration — httpx chunks the upload (see
                _ProgressTrackingReader), so this only needs to cover normal
                per-chunk network jitter, not total transfer time.
            connect_timeout: Seconds to wait for the TCP+TLS handshake.
            pool_timeout: Seconds to wait to acquire a pooled connection.

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
        self._last_detected_language: str | None = None
        logger.debug(
            f"TranscriptionClient initialized: model={model}, language={language}, "
            f"read_timeout={read_timeout}s, write_timeout={write_timeout}s"
        )
        # Split timeout: read scales with expected audio duration (set by the
        # caller, e.g. Pipeline, from max_audio_length); write/connect/pool
        # are small, fixed budgets since the upload is chunked (see
        # _ProgressTrackingReader) and therefore independent of file size.
        self.timeout = httpx.Timeout(
            read_timeout,
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=pool_timeout,
        )
        self._http_client = httpx.Client(timeout=self.timeout, follow_redirects=True)
        self.client = Mistral(api_key=self.api_key, client=self._http_client)

    def _report_progress(
        self,
        message: str,
        percent: int | None,
        segment_number: int | None,
        total_segments: int | None,
    ) -> None:
        """Invoke the progress callback if verbose progress reporting is enabled."""
        callback = self.progress_callback
        if callback and segment_number and total_segments:
            callback(message, percent)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(4),
        wait=tenacity.wait_exponential_jitter(initial=2, max=30, jitter=2),
        retry=tenacity.retry_if_exception(_is_retryable_transcription_error),
        reraise=True,
    )
    def _call_mistral_transcription(
        self,
        model: str,
        audio_path: str,
        language: str | None,
        segment_number: int | None,
        total_segments: int | None,
    ) -> Any:
        """Call Mistral audio transcription API with retry, streaming the file.

        Note: no timeout is passed to ``complete()`` here — it falls back to
        ``httpx.USE_CLIENT_DEFAULT``, i.e. the split ``httpx.Timeout``
        configured on ``self._http_client`` in ``__init__``.

        Retries reopen the file fresh on every attempt (tenacity re-invokes
        this whole method), so a partially-consumed stream from a failed
        attempt is never resent — no explicit seek bookkeeping needed.

        Args:
            model: Model name
            audio_path: Path to audio file
            language: Optional language code
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)

        Returns:
            Mistral transcription response

        Raises:
            Exception: On API error after all retries exhausted
        """
        file_size = os.path.getsize(audio_path)
        mb_total = file_size / (1024 * 1024)

        def on_progress(bytes_read: int, total: int) -> None:
            pct = int(100 * bytes_read / total) if total else 100
            mb_done = bytes_read / (1024 * 1024)
            self._report_progress(
                f"Uploading segment {segment_number}/{total_segments}: "
                f"{mb_done:.1f} / {mb_total:.1f} MB ({pct}%)",
                pct,
                segment_number,
                total_segments,
            )

        # Explicit 0% before any bytes are read: for files at or under
        # httpx's ~64KB multipart chunk size, the reader's very first (and
        # only) real read call already reaches 100%, so 0% would otherwise
        # never be reported.
        self._report_progress(
            f"Uploading segment {segment_number}/{total_segments}: 0 / {mb_total:.1f} MB (0%)",
            0,
            segment_number,
            total_segments,
        )

        with io.FileIO(audio_path, "rb") as raw:
            reader = _ProgressTrackingReader(raw, file_size, on_progress)
            file_obj = File(
                content=reader,
                file_name=Path(audio_path).name,
                content_type="audio/wav",
            )
            # Pass UNSET (the SDK's sentinel default) instead of None when no
            # language is requested. This is deliberate: the SDK types `language`
            # as `OptionalNullable[str] = UNSET`, and `complete()` only serializes
            # a field onto the wire when it is not UNSET. Passing `None` would send
            # `language: null`; passing UNSET omits the field entirely.
            #
            # Wire-semantics confirmed (M5.7, live Mistral call): a `language`-
            # omitted request and an explicit `language=None` request return
            # equivalent transcripts/usage, so UNSET (== "omitted") is the safe,
            # behavior-preserving choice and matches what the SDK does when the
            # argument is left out.
            response = self.client.audio.transcriptions.complete(
                model=model,
                file=file_obj,
                language=language if language else UNSET,
            )
        self._report_progress(
            f"Segment {segment_number}/{total_segments}: uploaded, waiting for transcription...",
            None,
            segment_number,
            total_segments,
        )
        return response

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(4),
        wait=tenacity.wait_exponential_jitter(initial=2, max=30, jitter=2),
        retry=tenacity.retry_if_exception(_is_retryable_transcription_error),
        reraise=True,
    )
    def _call_mistral_transcription_with_timestamps(
        self,
        model: str,
        audio_path: str,
        segment_number: int | None,
        total_segments: int | None,
    ) -> Any:
        """Call Mistral audio transcription API with timestamps, streaming the file.

        See ``_call_mistral_transcription`` for the timeout/retry/streaming
        rationale — identical here, just with ``timestamp_granularities``
        instead of ``language``.

        Args:
            model: Model name
            audio_path: Path to audio file
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)

        Returns:
            Mistral transcription response with segments

        Raises:
            Exception: On API error after all retries exhausted
        """
        file_size = os.path.getsize(audio_path)
        mb_total = file_size / (1024 * 1024)

        def on_progress(bytes_read: int, total: int) -> None:
            pct = int(100 * bytes_read / total) if total else 100
            mb_done = bytes_read / (1024 * 1024)
            self._report_progress(
                f"Uploading segment {segment_number}/{total_segments}: "
                f"{mb_done:.1f} / {mb_total:.1f} MB ({pct}%)",
                pct,
                segment_number,
                total_segments,
            )

        # Explicit, properly-typed kwargs (no `**kwargs` dict-splat): mypy
        # rejects `complete(**dict[str, object])` against the SDK's precise
        # overloads, so each argument is named and typed. The granularity list
        # is annotated as `list[TimestampGranularity]` because the SDK expects
        # `Optional[List[Literal["segment", "word"]]]`, not a bare `list[str]`.
        # Verified against the live Mistral API (M5.7).
        timestamp_granularities: list[TimestampGranularity] = ["segment"]

        # Explicit 0% before any bytes are read: for files at or under
        # httpx's ~64KB multipart chunk size, the reader's very first (and
        # only) real read call already reaches 100%, so 0% would otherwise
        # never be reported.
        self._report_progress(
            f"Uploading segment {segment_number}/{total_segments}: 0 / {mb_total:.1f} MB (0%)",
            0,
            segment_number,
            total_segments,
        )

        with io.FileIO(audio_path, "rb") as raw:
            reader = _ProgressTrackingReader(raw, file_size, on_progress)
            file_obj = File(
                content=reader,
                file_name=Path(audio_path).name,
                content_type="audio/wav",
            )
            response = self.client.audio.transcriptions.complete(
                model=model,
                file=file_obj,
                timestamp_granularities=timestamp_granularities,
            )
        self._report_progress(
            f"Segment {segment_number}/{total_segments}: uploaded, waiting for transcription...",
            None,
            segment_number,
            total_segments,
        )
        return response

    def _capture_usage(self, response: Any) -> None:
        """Store Mistral response usage stats (for cost calculation), if present."""
        if hasattr(response, "usage"):
            usage_obj = response.usage
            if hasattr(usage_obj, "model_dump"):
                self._last_usage = usage_obj.model_dump()
            elif isinstance(usage_obj, dict):
                self._last_usage = usage_obj.copy()

    def _capture_language(self, response: Any) -> None:
        """Store Mistral's detected audio language, if the response reports one."""
        self._last_detected_language = getattr(response, "language", None)

    def transcribe_audio(
        self,
        audio_path: str,
        language: str | None = None,
        segment_number: int | None = None,
        total_segments: int | None = None,
    ) -> str:
        """Transcribe audio file to text with automatic retry on transient failures.

        Args:
            audio_path: Path to audio file
            language: Optional language code. Overrides instance default if provided.
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)

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

            logger.debug(f"Calling Mistral API: model={self.model}, language={lang}")
            response = self._call_mistral_transcription(
                model=self.model,
                audio_path=audio_path,
                language=lang,
                segment_number=segment_number,
                total_segments=total_segments,
            )
            logger.debug(
                f"Transcription response received, text length: {len(response.text)}"
            )
            self._capture_usage(response)
            return str(response.text)
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
        """Transcribe audio with timestamp information and automatic retry on transient failures.

        Args:
            audio_path: Path to audio file
            language: Optional language code. Overrides instance default if provided.
                Note: language is not compatible with timestamps per Mistral docs.
            segment_number: Optional segment number (for progress reporting)
            total_segments: Optional total segments (for progress reporting)

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

            logger.debug("Calling Mistral API with timestamps")
            response = self._call_mistral_transcription_with_timestamps(
                model=self.model,
                audio_path=audio_path,
                segment_number=segment_number,
                total_segments=total_segments,
            )
            logger.debug(f"Transcription response type: {type(response)}")
            self._capture_usage(response)
            self._capture_language(response)

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
