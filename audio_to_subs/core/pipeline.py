"""Pipeline orchestrator for video to subtitles conversion.

Supports single video processing and batch processing of multiple videos.
Adds structured progress callbacks and cancellation support for v2.
"""

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional, TypedDict
from uuid import uuid4

from audio_to_subs.core.audio_extractor import (
    AudioExtractionError,
    FFmpegNotFoundError,
    extract_audio,
)
from audio_to_subs.core.audio_splitter import (
    get_audio_duration,
    split_audio,
)
from audio_to_subs.core.cancel import Cancelled, CancelToken
from audio_to_subs.core.models import DEFAULT_MAX_AUDIO_LENGTH
from audio_to_subs.core.subtitle_generator import (
    SubtitleFileExistsError,
    SubtitleFormatError,
    SubtitleGenerator,
)

__all__ = [
    "Pipeline",
    "PipelineResult",
    "SubtitleFileExistsError",
    "SubtitleFormatError",
]
from audio_to_subs.core.transcription_client import (
    TranscriptionClient,
    TranscriptionError,
)

logger = logging.getLogger(__name__)


# Type definitions for structured progress
class ProgressEvent(TypedDict, total=False):
    """Structured progress event for v2 pipeline."""

    stage: Literal["init", "extract", "split", "transcribe", "generate", "done"]
    percent: int
    message: str
    segment_index: int
    segment_count: int
    audio_duration_seconds: float
    mistral_usage: dict[str, Any]
    step_index: int | None
    step_total: int | None


StructuredProgressCallback = Callable[[ProgressEvent], None]
ProgressCallback = Callable[[str, Optional[int]], None]

# Matches the trailing "(XX.X%)" ffmpeg reports in its -progress output, so the
# extract/split sub-progress callback can recover a numeric percentage.
_PERCENT_RE = re.compile(r"\(([\d.]+)%\)")


@dataclass
class PipelineResult:
    """Result of pipeline video processing.

    Compatible with str usage (path operations) for backwards compatibility.
    """

    output_path: str
    audio_duration_seconds: float
    mistral_usage: dict[str, Any] | None
    segments_count: int
    detected_language: str | None = None

    def __fspath__(self) -> str:
        """Return the output path for filesystem operations."""
        return self.output_path

    def __str__(self) -> str:
        """Return the output path for string operations."""
        return self.output_path

    def __repr__(self) -> str:
        """Return a detailed representation."""
        return (
            f"PipelineResult("
            f"output_path={self.output_path!r}, "
            f"audio_duration_seconds={self.audio_duration_seconds}, "
            f"segments_count={self.segments_count}, "
            f"mistral_usage={self.mistral_usage is not None})"
        )


class PipelineError(Exception):
    """Raised when pipeline processing fails."""

    pass


class Pipeline:
    """Orchestrate video to subtitles conversion pipeline.

    Supports both legacy (message, percentage) and structured progress callbacks.
    Supports cooperative cancellation via CancelToken.
    """

    def __init__(
        self,
        api_key: str,
        progress_callback: Optional[ProgressCallback] = None,
        temp_dir: Optional[str] = None,
        transcription_model: str = "voxtral-mini-2602",
        language: Optional[str] = None,
        verbose_progress: bool = False,
        *,
        structured_progress_callback: Optional[StructuredProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
        max_audio_length: int = DEFAULT_MAX_AUDIO_LENGTH,
        language_mode: Literal["auto", "explicit"] = "explicit",
        overwrite: bool = False,
    ) -> None:
        """Initialize pipeline.

        Args:
            api_key: Mistral AI API key
            progress_callback: Optional legacy callback for progress updates (message, percentage)
            temp_dir: Optional temporary directory for intermediate files
            transcription_model: Mistral transcription model (default: voxtral-mini-2602)
            language: Optional language code for transcription (e.g., 'en', 'fr')
            verbose_progress: Enable detailed progress reporting (upload, segments)
            structured_progress_callback: Optional v2 callback receiving ProgressEvent dicts
            cancel_token: Optional v2 cancellation token for cooperative cancellation
            max_audio_length: Maximum audio segment length in seconds before splitting
            language_mode: "explicit" uses `language` as the output filename's
                language code as-is. "auto" ignores `language` for naming and
                instead uses whatever language Mistral's response reports it
                detected (falling back to "und" if it reports none).
            overwrite: When True, allow the generator to replace an existing
                output subtitle file (M6.g write-time guard). Default False.

        Raises:
            ValueError: If API key is not provided
        """
        if not api_key:
            raise ValueError("API key is required")

        self.api_key = api_key
        self.progress_callback = progress_callback
        self._structured_progress_callback = structured_progress_callback
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self.verbose_progress = verbose_progress
        self._cancel_token = cancel_token
        self.max_audio_length = max_audio_length
        logger.debug(
            f"Pipeline initialized: model={transcription_model}, language={language}, "
            f"temp_dir={self.temp_dir}, verbose_progress={verbose_progress}, "
            f"max_audio_length={max_audio_length}"
        )
        self.transcription_client = TranscriptionClient(
            api_key=api_key,
            model=transcription_model,
            language=language,
            progress_callback=self.progress_callback if verbose_progress else None,
        )
        self.subtitle_generator = SubtitleGenerator()
        self._language = language
        self._language_mode = language_mode
        # M6.g: whether an existing output file may be replaced at write time.
        self._overwrite = overwrite
        # Step accounting. ``_step_total`` is resolved once we know the audio
        # duration (after extraction): 4 if splitting occurs, else 3. ``None``
        # until then (init stage, before extraction completes).
        self._step_total: int | None = None

    def _check_cancel(self) -> None:
        """Check if cancellation has been requested and raise Cancelled if so."""
        if self._cancel_token is not None:
            self._cancel_token.check()

    def _subprogress_callback(
        self, stage: Literal["extract", "split"], lo: int, hi: int
    ) -> Optional[Callable[[str], None]]:
        """Build a ffmpeg sub-progress callback for ``extract``/``split``.

        Returns a ``Callable[[str], None]`` matching the signature
        ``extract_audio``/``split_audio`` expect from ``_parse_ffmpeg_progress``
        (a message string with a trailing ``(XX.X%)``). It parses ffmpeg's own
        time-based percentage out of that message and maps it linearly into the
        stage's percent sub-range ``[lo, hi]``, then forwards it through
        ``_emit_progress``. This drives continuous interior progress during the
        (potentially long) ffmpeg decode — independent of ``verbose_progress``,
        gated only on whether a structured callback is configured (the worker
        path). Returns None when no structured callback is set.

        M5.8 (#1, verified): previously the worker built the pipeline with
        ``verbose_progress=False``, so no ffmpeg progress callback was wired and
        long decodes showed a single 10%->25% jump. This is the fix; do NOT
        re-gate on ``verbose_progress``.
        """
        if self._structured_progress_callback is None:
            return None

        def _cb(message: str) -> None:
            match = _PERCENT_RE.search(message)
            if not match:
                return
            ratio = min(100.0, max(0.0, float(match.group(1)))) / 100.0
            mapped = int(lo + (hi - lo) * ratio)
            self._emit_progress(stage, message, mapped)

        return _cb

    def _step_for(
        self,
        stage: Literal["init", "extract", "split", "transcribe", "generate", "done"],
    ) -> tuple[Optional[int], Optional[int]]:
        """Return ``(step_index, step_total)`` for a pipeline stage.

        ``init`` and ``done`` are not numbered steps (init is hidden, done is
        terminal), so they return ``(None, None)``. ``step_total`` is ``None``
        until resolved after extraction (when we know whether splitting occurs).

        M5.8 (#4, verified): step numbering decided as extract=1, init hidden,
        done terminal (step_total 3 w/o split, 4 w/ split). ``step_index``/
        ``step_total`` are also persisted (progress_stage/step_* columns) so a
        refresh mid-job reconstructs the step — see worker/progress.py.
        """
        if self._step_total is None or stage in ("init", "done"):
            return (None, None)
        if self._step_total == 4:
            mapping = {
                "extract": 1,
                "split": 2,
                "transcribe": 3,
                "generate": 4,
            }
        else:
            mapping = {
                "extract": 1,
                "transcribe": 2,
                "generate": 3,
            }
        return (mapping.get(stage), self._step_total)

    def _emit_progress(
        self,
        stage: Literal["init", "extract", "split", "transcribe", "generate", "done"],
        message: str,
        percent: Optional[int] = None,
        **extra: Any,
    ) -> None:
        """Emit progress to both legacy and structured callbacks.

        Args:
            stage: Current pipeline stage
            message: Progress message
            percent: Optional percentage (0-100)
            **extra: Additional fields for structured progress
        """
        # Legacy callback
        if self.progress_callback:
            self.progress_callback(message, percent if self.verbose_progress else None)

        # Structured callback
        if self._structured_progress_callback:
            event: ProgressEvent = {"stage": stage, "message": message}
            if percent is not None:
                event["percent"] = percent
            step_index, step_total = self._step_for(stage)
            if step_index is not None:
                event["step_index"] = step_index
                event["step_total"] = step_total
            # extra is a **kwargs dict[str, Any]; TypedDict.update() can't
            # verify its keys/types match ProgressEvent's schema statically.
            event.update(extra)  # type: ignore[typeddict-item]
            self._structured_progress_callback(event)

    def process_batch(self, jobs: list[dict[str, str]]) -> dict[str, PipelineResult]:
        """Process multiple videos in batch.

        Args:
            jobs: List of dicts with 'input', 'output', and optional 'format' keys

        Returns:
            Dict mapping input paths to PipelineResult objects

        Raises:
            PipelineError: If any job fails
        """
        results = {}
        total = len(jobs)

        for idx, job in enumerate(jobs, 1):
            input_path = job["input"]
            output_path = job["output"]
            output_format = job.get("format", "srt")

            self._emit_progress(
                "init",
                f"[{idx}/{total}] Processing: {input_path}",
                percent=0,
            )

            try:
                result = self.process_video(input_path, output_path, output_format)
                results[input_path] = result
            except PipelineError as e:
                self._emit_progress(
                    "init",
                    f"Failed: {input_path} - {str(e)}",
                    percent=100,
                )
                # Log failure but continue processing other jobs in batch
                logger.error(f"Job failed: {input_path} - {str(e)}")
            except Cancelled:
                self._emit_progress(
                    "init",
                    f"Cancelled: {input_path}",
                    percent=100,
                )
                raise

        return results

    def process_video(
        self,
        video_path: str,
        output_path: str,
        output_format: str = "srt",
    ) -> PipelineResult:
        """Convert video to subtitles.

        Args:
            video_path: Path to input video file
            output_path: Path to write output subtitle file
            output_format: Output subtitle format (srt, vtt, webvtt, sbv). Default: srt

        Returns:
            PipelineResult with output path and metadata

        Raises:
            PipelineError: If any stage fails
            Cancelled: If cancellation was requested via cancel_token
        """
        audio_path: str | None = None
        audio_segments: list[str] = []
        audio_duration_seconds: float = 0.0
        mistral_usage: dict[str, Any] | None = None
        segments_count: int = 0

        logger.debug(
            f"process_video: video_path={video_path}, output_format={output_format}"
        )
        self._emit_progress("init", "Starting pipeline", percent=0)

        try:
            # Stage 1: Extract audio and get duration (0-25%)
            audio_path, audio_duration_seconds = self._extract_and_prepare_audio(
                video_path
            )
            self._check_cancel()

            # Stage 2: Handle audio splitting if needed (>15 minutes) (25-30%)
            audio_segments = self._handle_audio_splitting(
                audio_path, audio_duration_seconds
            )
            self._check_cancel()

            # Stage 3: Transcribe audio segments (30-75%)
            all_segments, mistral_usage, detected_language = (
                self._perform_transcription(audio_segments)
            )
            segments_count = len(all_segments)
            logger.debug(f"Transcription complete: {segments_count} segments")
            self._emit_progress(
                "transcribe",
                "Transcription processing complete",
                percent=75,
                mistral_usage=mistral_usage,
            )
            self._check_cancel()

            # Resolve the language code that drives the output filename: in
            # auto mode this is whatever Mistral actually detected (or "und"
            # if it reported nothing), never the originally requested code.
            effective_language: str | None
            if self._language_mode == "auto":
                effective_language = detected_language or "und"
            else:
                effective_language = self._language

            # Stage 4: Generate subtitles and finalize (75-100%)
            result_path = self._finalize_subtitles(
                all_segments,
                output_path,
                output_format,
                audio_duration_seconds,
                mistral_usage,
                effective_language,
                overwrite=self._overwrite,
            )

            return PipelineResult(
                output_path=result_path,
                audio_duration_seconds=audio_duration_seconds,
                mistral_usage=mistral_usage,
                segments_count=segments_count,
                detected_language=detected_language,
            )

        except Cancelled:
            # Cleanup before re-raising
            self._cleanup_audio_files(audio_path, audio_segments)
            raise

        finally:
            # Cleanup temp audio files
            self._cleanup_audio_files(audio_path, audio_segments)

    def _cleanup_audio_files(
        self, audio_path: str | None, audio_segments: list[str]
    ) -> None:
        """Clean up temporary audio files."""
        if audio_path and Path(audio_path).exists():
            try:
                os.remove(audio_path)
            except OSError:
                pass

        for segment_path in audio_segments:
            if segment_path != audio_path and Path(segment_path).exists():
                try:
                    os.remove(segment_path)
                except OSError:
                    pass

    def _extract_audio(self, video_path: str) -> str:
        """Extract audio from video.

        Args:
            video_path: Path to video file

        Returns:
            Path to extracted audio file

        Raises:
            PipelineError: If extraction fails
            Cancelled: If cancellation was requested
        """
        try:
            video_file = Path(video_path)
            if not video_file.exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")

            logger.debug(f"Video file size: {video_file.stat().st_size} bytes")

            # Generate temp audio file path (include uuid to avoid collision in concurrent batch jobs)
            audio_path = (
                Path(self.temp_dir) / f"audio_{video_file.stem}_{uuid4().hex[:8]}.wav"
            )

            # Pass cancel_token to audio extractor. The structured sub-progress
            # callback drives continuous ffmpeg time-based progress during the
            # (potentially long) decode, independent of verbose_progress.
            return extract_audio(
                video_path,
                str(audio_path),
                progress_callback=self._subprogress_callback("extract", 10, 25),
                cancel_token=self._cancel_token,
            )

        except FileNotFoundError as e:
            logger.error(f"Video file not found: {video_path}")
            raise PipelineError(f"Video file not found: {str(e)}") from e
        except (FFmpegNotFoundError, AudioExtractionError) as e:
            logger.error(f"Audio extraction failed: {str(e)}")
            raise PipelineError(f"Audio extraction failed: {str(e)}") from e
        except Cancelled:
            # Clean up partial extraction
            if audio_path and Path(audio_path).exists():
                try:
                    os.remove(audio_path)
                except OSError:
                    pass
            raise
        except Exception as e:
            logger.error(f"Audio extraction error: {str(e)}")
            raise PipelineError(f"Audio extraction failed: {str(e)}") from e

    def _extract_and_prepare_audio(self, video_path: str) -> tuple[str, float]:
        """Extract audio from video and get its duration.

        Args:
            video_path: Path to video file

        Returns:
            Tuple of (audio_path, audio_duration_seconds)

        Raises:
            PipelineError: If extraction or duration detection fails
        """
        # Stage 1: Extract audio (0-25%)
        self._emit_progress("extract", "Extracting audio from video...", percent=10)
        self._check_cancel()

        audio_path = self._extract_audio(video_path)
        logger.debug(f"Audio extracted: {audio_path}")

        # Get audio duration (D6: single call cached here)
        audio_duration_seconds = get_audio_duration(audio_path)
        logger.debug(f"Audio duration: {audio_duration_seconds} seconds")

        # Resolve step accounting now that we know whether splitting will occur.
        self._step_total = 4 if audio_duration_seconds > self.max_audio_length else 3

        self._emit_progress(
            "extract",
            "Audio extraction complete",
            percent=25,
            audio_duration_seconds=audio_duration_seconds,
        )

        return audio_path, audio_duration_seconds

    def _handle_audio_splitting(
        self, audio_path: str, audio_duration_seconds: float
    ) -> list[str]:
        """Check if audio needs splitting and split if necessary.

        Args:
            audio_path: Path to audio file
            audio_duration_seconds: Duration of audio in seconds

        Returns:
            List of audio segment paths (single item if no splitting needed)

        Raises:
            PipelineError: If splitting fails
            Cancelled: If cancellation was requested
        """
        # Stage 2: Check if audio needs splitting (configurable threshold)
        # D6: Dedup get_audio_duration by using cached duration instead of calling needs_splitting
        if audio_duration_seconds > self.max_audio_length:
            self._emit_progress(
                "split",
                f"Audio exceeds {self.max_audio_length}s, splitting into segments...",
                percent=25,
            )
            self._check_cancel()

            audio_segments = split_audio(
                audio_path,
                self.temp_dir,
                max_length=self.max_audio_length,
                progress_callback=self._subprogress_callback("split", 25, 30),
                cancel_token=self._cancel_token,
            )
            logger.debug(f"Audio split into {len(audio_segments)} segments")
            self._emit_progress(
                "split",
                f"Split audio into {len(audio_segments)} segments",
                percent=30,
            )
        else:
            audio_segments = [audio_path]
            logger.debug("Audio does not need splitting")
            self._emit_progress(
                "split",
                "Audio ready for transcription",
                percent=30,
            )

        self._check_cancel()
        return audio_segments

    def _perform_transcription(
        self, audio_segments: list[str]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
        """Transcribe audio segments.

        Args:
            audio_segments: List of audio segment paths to transcribe

        Returns:
            Tuple of (all_segments, mistral_usage, detected_language)

        Raises:
            PipelineError: If transcription fails
            Cancelled: If cancellation was requested
        """
        # Stage 3: Transcribe audio (30-75%)
        self._emit_progress(
            "transcribe", "Transcribing audio with Mistral AI...", percent=30
        )
        self._check_cancel()

        return self._transcribe_audio_segments(audio_segments)

    def _finalize_subtitles(
        self,
        all_segments: list[dict[str, Any]],
        output_path: str,
        output_format: str,
        audio_duration_seconds: float,
        mistral_usage: dict[str, Any] | None,
        effective_language: str | None,
        overwrite: bool = False,
    ) -> str:
        """Generate subtitles and emit final progress event.

        Args:
            all_segments: Transcribed segments
            output_path: Path to write subtitle file
            output_format: Output subtitle format
            audio_duration_seconds: Total audio duration
            mistral_usage: Usage metrics from transcription
            effective_language: Resolved language code to use for the output
                filename (the explicit selection, or the auto-detected/"und"
                code in auto mode)

        Returns:
            Path to generated subtitle file

        Raises:
            PipelineError: If generation fails
            Cancelled: If cancellation was requested
        """
        # Stage 4: Generate subtitles (75-100%)
        self._emit_progress(
            "generate",
            f"Generating {output_format.upper()} subtitles...",
            percent=75,
        )
        self._check_cancel()

        result_path = self._generate_subtitles(
            all_segments,
            output_path,
            output_format,
            effective_language,
            overwrite=overwrite,
        )
        logger.debug(f"Subtitles generated: {result_path}")

        self._emit_progress(
            "generate",
            "Subtitle generation complete",
            percent=100,
        )
        self._check_cancel()

        # Final done event
        self._emit_progress(
            "done",
            "Complete! Subtitles generated successfully.",
            percent=100,
            audio_duration_seconds=audio_duration_seconds,
            mistral_usage=mistral_usage,
        )

        return result_path

    def _transcribe_audio_segments(
        self, audio_segments: list[str]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
        """Transcribe multiple audio segments and merge timestamps.

        Args:
            audio_segments: List of audio file paths to transcribe

        Returns:
            Tuple of (all merged segments, mistral_usage dict or None,
            detected_language or None)

        Raises:
            PipelineError: If transcription fails
            Cancelled: If cancellation was requested
        """
        try:
            all_segments: list[dict[str, Any]] = []
            time_offset = 0.0
            total_segments = len(audio_segments)
            mistral_usage: dict[str, Any] | None = None
            detected_language: str | None = None

            for idx, segment_path in enumerate(audio_segments, 1):
                self._check_cancel()

                # Transcribe this segment
                segments, usage, lang = self._transcribe_single_segment(
                    segment_path, idx, total_segments
                )

                # Extract usage/detected language from the last segment's response
                if idx == len(audio_segments):
                    if usage:
                        mistral_usage = usage
                    detected_language = lang

                # Reject if no timestamped segments
                if not segments:
                    raise PipelineError(
                        f"Transcription failed: AI service did not return "
                        f"timestamp data for segment {idx}. "
                        f"Cannot generate accurate subtitles without timestamps."
                    )

                # Adjust timestamps and add to all_segments
                all_segments, time_offset = self._adjust_segment_timestamps(
                    segments, all_segments, time_offset
                )

                self._emit_progress(
                    "transcribe",
                    f"Completed segment {idx}/{total_segments}",
                    percent=30 + int(45 * (idx / total_segments)),
                    segment_index=idx,
                    segment_count=total_segments,
                )

            return all_segments, mistral_usage, detected_language

        except TranscriptionError as e:
            raise PipelineError(f"Transcription failed: {str(e)}") from e
        except PipelineError:
            # Bubble up explicit pipeline errors
            raise
        except Exception as e:
            raise PipelineError(f"Transcription failed: {str(e)}") from e

    def _transcribe_single_segment(
        self, segment_path: str, segment_index: int, total_segments: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
        """Transcribe a single audio segment.

        Args:
            segment_path: Path to audio segment file
            segment_index: 1-based index of this segment
            total_segments: Total number of segments

        Returns:
            Tuple of (transcribed_segments, mistral_usage or None,
            detected_language or None)

        Raises:
            TranscriptionError: If transcription fails
        """
        # Calculate progress percentage for this segment
        segment_start_percent = 30 + int(45 * ((segment_index - 1) / total_segments))

        self._emit_progress(
            "transcribe",
            f"Transcribing segment {segment_index}/{total_segments}...",
            percent=segment_start_percent,
            segment_index=segment_index,
            segment_count=total_segments,
        )

        # Pass segment info to transcription client for detailed progress
        segments = self.transcription_client.transcribe_audio_with_timestamps(
            segment_path,
            segment_number=segment_index if self.verbose_progress else None,
            total_segments=total_segments if self.verbose_progress else None,
        )

        # Extract usage/detected language from the transcription response
        # The Mistral response is on the transcription client
        usage = getattr(self.transcription_client, "_last_usage", None)
        detected_language = getattr(
            self.transcription_client, "_last_detected_language", None
        )

        return segments, usage, detected_language

    def _adjust_segment_timestamps(
        self,
        segments: list[dict[str, Any]],
        all_segments: list[dict[str, Any]],
        time_offset: float,
    ) -> tuple[list[dict[str, Any]], float]:
        """Adjust timestamps for audio segments based on concatenation position.

        Args:
            segments: Segments from current transcription
            all_segments: Accumulated segments from previous transcriptions
            time_offset: Time offset to apply (end time of previous segment)

        Returns:
            Tuple of (updated_all_segments, new_time_offset)
        """
        # Adjust timestamps based on position in overall audio
        for segment in segments:
            segment["start"] += time_offset
            segment["end"] += time_offset
            all_segments.append(segment)

        # Update time offset for next segment
        new_offset = segments[-1]["end"] if segments else time_offset

        return all_segments, new_offset

    def _generate_subtitles(
        self,
        segments: list[dict[str, Any]],
        output_path: str,
        output_format: str = "srt",
        language_code: Optional[str] = None,
        overwrite: bool = False,
    ) -> str:
        """Generate subtitle file in specified format.

        Args:
            segments: Transcription segments
            output_path: Path to write subtitle file
            output_format: Output subtitle format (srt, vtt, webvtt, sbv)
            language_code: Optional language code for filename
            overwrite: When True, allow replacing an existing output file
                (M6.g write-time guard). Default False.

        Returns:
            Path to generated subtitle file

        Raises:
            PipelineError: If generation fails (but NOT SubtitleFileExistsError,
                which is propagated so the worker can mark the job accordingly)
        """
        try:
            return self.subtitle_generator.generate(
                segments,
                output_path,
                output_format,
                language_code,
                overwrite=overwrite,
            )
        except SubtitleFileExistsError:
            # Propagate as-is: the worker turns this into a FAILED job with an
            # `output_exists` error rather than a generic failure.
            raise
        except SubtitleFormatError as e:
            raise PipelineError(f"Subtitle generation failed: {str(e)}") from e
        except Exception as e:
            raise PipelineError(f"Subtitle generation failed: {str(e)}") from e
