"""Pipeline orchestrator for video to subtitles conversion.

Supports single video processing and batch processing of multiple videos.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.audio_extractor import extract_audio, FFmpegNotFoundError, AudioExtractionError
from src.transcription_client import TranscriptionClient, TranscriptionError
from src.audio_splitter import (
    get_audio_duration,
    split_audio,
    needs_splitting,
)
from typing import Any

from src.subtitle_generator import SubtitleGenerator, SubtitleFormatError

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Raised when pipeline processing fails."""

    pass


class Pipeline:
    """Orchestrate video to subtitles conversion pipeline."""

    def __init__(
        self,
        api_key: str,
        progress_callback: Optional[Callable[[str], None]] = None,
        temp_dir: Optional[str] = None,
        transcription_model: str = "voxtral-mini-latest",
        language: Optional[str] = None,
        verbose_progress: bool = False,
    ):
        """Initialize pipeline.

        Args:
            api_key: Mistral AI API key
            progress_callback: Optional callback for progress updates
            temp_dir: Optional temporary directory for intermediate files
            transcription_model: Mistral transcription model (default: voxtral-mini-latest)
            language: Optional language code for transcription (e.g., 'en', 'fr')
            verbose_progress: Enable detailed progress reporting (upload, segments)

        Raises:
            ValueError: If API key is not provided
        """
        if not api_key:
            raise ValueError("API key is required")

        self.api_key = api_key
        self.progress_callback = progress_callback
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self.verbose_progress = verbose_progress
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

    def process_batch(self, jobs: list[dict[str, str]]) -> dict[str, str]:
        """Process multiple videos in batch.

        Args:
            jobs: List of dicts with 'input', 'output', and optional 'format' keys

        Returns:
            Dict mapping input paths to output paths

        Raises:
            PipelineError: If any job fails
        """
        results = {}
        total = len(jobs)

        for idx, job in enumerate(jobs, 1):
            input_path = job["input"]
            output_path = job["output"]
            output_format = job.get("format", "srt")

            self._progress(f"[{idx}/{total}] Processing: {input_path}")

            try:
                result = self.process_video(input_path, output_path, output_format)
                results[input_path] = result
            except PipelineError as e:
                self._progress(f"Failed: {input_path} - {str(e)}")
                raise

        return results

    def process_video(
        self, video_path: str, output_path: str, output_format: str = "srt"
    ) -> str:
        """Convert video to subtitles.

        Args:
            video_path: Path to input video file
            output_path: Path to write output subtitle file
            output_format: Output subtitle format (srt, vtt, webvtt, sbv). Default: srt

        Returns:
            Path to generated subtitle file

        Raises:
            PipelineError: If any stage fails
        """
        audio_path = None
        audio_segments: list[str] = []

        logger.debug(f"process_video: video_path={video_path}, output_format={output_format}")
        try:
            # Stage 1: Extract audio
            self._progress("Extracting audio from video...")
            audio_path = self._extract_audio(video_path)
            logger.debug(f"Audio extracted: {audio_path}")

            # Stage 2: Check if audio needs splitting (>15 minutes)
            if needs_splitting(audio_path):
                self._progress("Audio exceeds 15 minutes, splitting into segments...")
                audio_segments = split_audio(
                    audio_path,
                    self.temp_dir,
                    progress_callback=self.progress_callback if self.verbose_progress else None,
                )
                logger.debug(f"Audio split into {len(audio_segments)} segments")
                self._progress(f"Split audio into {len(audio_segments)} segments")
            else:
                audio_segments = [audio_path]
                logger.debug("Audio does not need splitting")

            # Stage 3: Transcribe audio (handling multiple segments if needed)
            self._progress("Transcribing audio with Mistral AI...")
            all_segments = self._transcribe_audio_segments(audio_segments)
            logger.debug(f"Transcription complete: {len(all_segments)} segments")

            # Stage 4: Generate subtitles
            self._progress(f"Generating {output_format.upper()} subtitles...")
            output = self._generate_subtitles(all_segments, output_path, output_format)
            logger.debug(f"Subtitles generated: {output}")

            self._progress("Complete! Subtitles generated successfully.")
            return output

        finally:
            # Cleanup temp audio file
            if audio_path and Path(audio_path).exists():
                try:
                    os.remove(audio_path)
                except OSError:
                    pass  # Ignore cleanup errors

            # Cleanup audio segments
            for segment_path in audio_segments:
                if segment_path != audio_path and Path(segment_path).exists():
                    try:
                        os.remove(segment_path)
                    except OSError:
                        pass  # Ignore cleanup errors

    def _extract_audio(self, video_path: str) -> str:
        """Extract audio from video.

        Args:
            video_path: Path to video file

        Returns:
            Path to extracted audio file

        Raises:
            PipelineError: If extraction fails
        """
        try:
            video_file = Path(video_path)
            if not video_file.exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")

            logger.debug(f"Video file size: {video_file.stat().st_size} bytes")

            # Generate temp audio file path
            audio_path = Path(self.temp_dir) / f"audio_{video_file.stem}.wav"

            return extract_audio(
                video_path,
                str(audio_path),
                progress_callback=self.progress_callback if self.verbose_progress else None,
            )

        except FileNotFoundError as e:
            logger.error(f"Video file not found: {video_path}")
            raise PipelineError(f"Video file not found: {str(e)}") from e
        except (FFmpegNotFoundError, AudioExtractionError) as e:
            logger.error(f"Audio extraction failed: {str(e)}")
            raise PipelineError(f"Audio extraction failed: {str(e)}") from e
        except Exception as e:
            logger.error(f"Audio extraction error: {str(e)}")
            raise PipelineError(f"Audio extraction failed: {str(e)}") from e

    def _transcribe_audio_segments(
        self, audio_segments: list[str]
    ) -> list[dict[str, Any]]:
        """Transcribe multiple audio segments and merge timestamps.

        Args:
            audio_segments: List of audio file paths to transcribe

        Returns:
            List of merged transcription segments with adjusted timestamps

        Raises:
            PipelineError: If transcription fails
        """
        try:
            all_segments: list[dict[str, Any]] = []
            time_offset = 0.0

            for idx, segment_path in enumerate(audio_segments, 1):
                self._progress(f"Transcribing segment {idx}/{len(audio_segments)}...")
                # Pass segment info to transcription client for detailed progress
                segments = self.transcription_client.transcribe_audio_with_timestamps(
                    segment_path,
                    segment_number=idx if self.verbose_progress else None,
                    total_segments=(
                        len(audio_segments) if self.verbose_progress else None
                    ),
                )

                # Adjust timestamps based on position in overall audio
                for segment in segments:
                    segment["start"] += time_offset
                    segment["end"] += time_offset
                    all_segments.append(segment)

                # Update time offset for next segment
                if segments:
                    time_offset = segments[-1]["end"]

            return all_segments
        except TranscriptionError as e:
            raise PipelineError(f"Transcription failed: {str(e)}") from e
        except Exception as e:
            raise PipelineError(f"Transcription failed: {str(e)}") from e

    def _generate_subtitles(
        self, segments: List[Dict], output_path: str, output_format: str = "srt"
    ) -> str:
        """Generate subtitle file in specified format.

        Args:
            segments: Transcription segments
            output_path: Path to write subtitle file
            output_format: Output subtitle format (srt, vtt, webvtt, sbv)

        Returns:
            Path to generated subtitle file

        Raises:
            PipelineError: If generation fails
        """
        try:
            return self.subtitle_generator.generate(
                segments, output_path, output_format
            )
        except SubtitleFormatError as e:
            raise PipelineError(f"Subtitle generation failed: {str(e)}") from e
        except Exception as e:
            raise PipelineError(f"Subtitle generation failed: {str(e)}") from e

    def _progress(self, message: str) -> None:
        """Call progress callback if provided.

        Args:
            message: Progress message
        """
        if self.progress_callback:
            self.progress_callback(message)
