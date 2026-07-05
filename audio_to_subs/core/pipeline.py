"""Pipeline orchestrator for video to subtitles conversion.

Supports single video processing and batch processing of multiple videos.
Adds structured progress callbacks and cancellation support for v2.
"""

import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, TypedDict
from uuid import uuid4

from audio_to_subs.core.audio_extractor import (
    extract_audio,
    FFmpegNotFoundError,
    AudioExtractionError,
)
from audio_to_subs.core.transcription_client import (
    TranscriptionClient,
    TranscriptionError,
)
from audio_to_subs.core.audio_splitter import (
    split_audio,
    needs_splitting,
    get_audio_duration,
)
from audio_to_subs.core.subtitle_generator import (
    SubtitleGenerator,
    SubtitleFormatError,
)
from audio_to_subs.core.cancel import Cancelled, CancelToken

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


StructuredProgressCallback = Callable[[ProgressEvent], None]
ProgressCallback = Callable[[str, Optional[int]], None]


@dataclass
class PipelineResult:
    """Result of pipeline video processing.

    Compatible with str usage (path operations) for backwards compatibility.
    """

    output_path: str
    audio_duration_seconds: float
    mistral_usage: dict[str, Any] | None
    segments_count: int

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
    ) -> None:
        """Initialize pipeline.

        Args:
            api_key: Mistral AI API key
            progress_callback: Optional legacy callback for progress updates (message, percentage)
            temp_dir: Optional temporary directory for intermediate files
            transcription_model: Mistral transcription model (default: voxtral-mini-latest)
            language: Optional language code for transcription (e.g., 'en', 'fr')
            verbose_progress: Enable detailed progress reporting (upload, segments)
            structured_progress_callback: Optional v2 callback receiving ProgressEvent dicts
            cancel_token: Optional v2 cancellation token for cooperative cancellation

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
        logger.debug(
            f"Pipeline initialized: model={transcription_model}, language={language}, "
            f"temp_dir={self.temp_dir}, verbose_progress={verbose_progress}"
        )
        self.transcription_client = TranscriptionClient(
            api_key=api_key,
            model=transcription_model,
            language=language,
            progress_callback=self.progress_callback if verbose_progress else None,
        )
        self.subtitle_generator = SubtitleGenerator()
        self._language = language

    def _check_cancel(self) -> None:
        """Check if cancellation has been requested and raise Cancelled if so."""
        if self._cancel_token is not None:
            self._cancel_token.check()

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
            event.update(extra)
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
                result = self.process_video(
                    input_path, output_path, output_format
                )
                results[input_path] = result
            except PipelineError as e:
                self._emit_progress(
                    "init",
                    f"Failed: {input_path} - {str(e)}",
                    percent=100,
                )
                raise
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
            # Stage 1: Extract audio (0-25%)
            self._emit_progress("extract", "Extracting audio from video...", percent=10)
            self._check_cancel()

            audio_path = self._extract_audio(video_path)
            logger.debug(f"Audio extracted: {audio_path}")

            # Get audio duration
            audio_duration_seconds = get_audio_duration(audio_path)
            logger.debug(f"Audio duration: {audio_duration_seconds} seconds")

            self._emit_progress(
                "extract",
                "Audio extraction complete",
                percent=25,
                audio_duration_seconds=audio_duration_seconds,
            )
            self._check_cancel()

            # Stage 2: Check if audio needs splitting (>15 minutes)
            if needs_splitting(audio_path):
                self._emit_progress(
                    "split",
                    "Audio exceeds 15 minutes, splitting into segments...",
                    percent=25,
                )
                self._check_cancel()

                audio_segments = split_audio(
                    audio_path,
                    self.temp_dir,
                    progress_callback=self.progress_callback
                    if self.verbose_progress
                    else None,
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

            # Stage 3: Transcribe audio (handling multiple segments if needed) (30-75%)
            self._emit_progress("transcribe", "Transcribing audio with Mistral AI...", percent=30)
            self._check_cancel()

            all_segments, mistral_usage = self._transcribe_audio_segments(
                audio_segments
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
                self.transcription_client.language,
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

            return PipelineResult(
                output_path=result_path,
                audio_duration_seconds=audio_duration_seconds,
                mistral_usage=mistral_usage,
                segments_count=segments_count,
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
            audio_path = Path(self.temp_dir) / f"audio_{video_file.stem}_{uuid4().hex[:8]}.wav"

            # Only pass progress callback if verbose_progress is True
            progress_callback = (
                self.progress_callback if self.verbose_progress else None
            )

            # Pass cancel_token to audio extractor
            return extract_audio(
                video_path,
                str(audio_path),
                progress_callback=progress_callback,
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

    def _transcribe_audio_segments(
        self, audio_segments: list[str]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Transcribe multiple audio segments and merge timestamps.

        Args:
            audio_segments: List of audio file paths to transcribe

        Returns:
            Tuple of (all merged segments, mistral_usage dict or None)

        Raises:
            PipelineError: If transcription fails
            Cancelled: If cancellation was requested
        """
        try:
            all_segments: list[dict[str, Any]] = []
            time_offset = 0.0
            total_segments = len(audio_segments)
            mistral_usage: dict[str, Any] | None = None

            for idx, segment_path in enumerate(audio_segments, 1):
                self._check_cancel()

                # Calculate progress percentage for this segment
                segment_start_percent = 30 + int(45 * ((idx - 1) / total_segments))
                segment_end_percent = 30 + int(45 * (idx / total_segments))

                self._emit_progress(
                    "transcribe",
                    f"Transcribing segment {idx}/{total_segments}...",
                    percent=segment_start_percent,
                    segment_index=idx,
                    segment_count=total_segments,
                )

                # Pass segment info to transcription client for detailed progress
                segments = self.transcription_client.transcribe_audio_with_timestamps(
                    segment_path,
                    segment_number=idx if self.verbose_progress else None,
                    total_segments=total_segments if self.verbose_progress else None,
                )

                # Extract usage from the last segment's response
                # The Mistral response is on the transcription client
                if idx == len(audio_segments):
                    # Extract usage from the last transcription response
                    last_usage = getattr(self.transcription_client, "_last_usage", None)
                    if last_usage:
                        mistral_usage = last_usage

                # Reject if no timestamped segments
                if not segments:
                    raise PipelineError(
                        f"Transcription failed: AI service did not return "
                        f"timestamp data for segment {idx}. "
                        f"Cannot generate accurate subtitles without timestamps."
                    )

                # Adjust timestamps based on position in overall audio
                for segment in segments:
                    segment["start"] += time_offset
                    segment["end"] += time_offset
                    all_segments.append(segment)

                # Update time offset for next segment
                if segments:
                    time_offset = segments[-1]["end"]

                self._emit_progress(
                    "transcribe",
                    f"Completed segment {idx}/{total_segments}",
                    percent=segment_end_percent,
                    segment_index=idx,
                    segment_count=total_segments,
                )

            return all_segments, mistral_usage

        except TranscriptionError as e:
            raise PipelineError(f"Transcription failed: {str(e)}") from e
        except PipelineError:
            # Bubble up explicit pipeline errors
            raise
        except Exception as e:
            raise PipelineError(f"Transcription failed: {str(e)}") from e

    def _generate_subtitles(
        self,
        segments: List[Dict],
        output_path: str,
        output_format: str = "srt",
        language_code: Optional[str] = None,
    ) -> str:
        """Generate subtitle file in specified format.

        Args:
            segments: Transcription segments
            output_path: Path to write subtitle file
            output_format: Output subtitle format (srt, vtt, webvtt, sbv)
            language_code: Optional language code for filename

        Returns:
            Path to generated subtitle file

        Raises:
            PipelineError: If generation fails
        """
        try:
            return self.subtitle_generator.generate(
                segments, output_path, output_format, language_code
            )
        except SubtitleFormatError as e:
            raise PipelineError(f"Subtitle generation failed: {str(e)}") from e
        except Exception as e:
            raise PipelineError(f"Subtitle generation failed: {str(e)}") from e
