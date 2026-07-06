"""Audio extraction from video files using FFmpeg."""

import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional

from audio_to_subs.core.cancel import CancelToken
from audio_to_subs.core.ffmpeg_utils import (
    check_cancel_periodically as _check_cancel_periodically,
)
from audio_to_subs.core.ffmpeg_utils import (
    check_ffmpeg_available,
    probe_duration,
)
from audio_to_subs.core.ffmpeg_utils import (
    parse_ffmpeg_progress as _parse_ffmpeg_progress,
)

logger = logging.getLogger(__name__)


class FFmpegNotFoundError(Exception):
    """Raised when FFmpeg is not available on the system."""

    pass


class AudioExtractionError(Exception):
    """Raised when audio extraction fails."""

    pass


def _get_video_duration(video_path: str) -> float:
    """Get duration of video file in seconds.

    Args:
        video_path: Path to video file

    Returns:
        Duration in seconds

    Raises:
        AudioExtractionError: If duration cannot be determined
    """
    try:
        logger.debug(f"Getting video duration: {video_path}")
        duration = probe_duration(video_path)
        logger.debug(f"Video duration: {duration} seconds")
        return duration
    except (subprocess.CalledProcessError, ValueError) as e:
        logger.error(f"Failed to get video duration: {str(e)}")
        raise AudioExtractionError(f"Failed to get video duration: {str(e)}") from e


def extract_audio(  # noqa: C901
    video_path: str,
    output_path: str,
    progress_callback: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[CancelToken] = None,
) -> str:
    """Extract audio from video file using FFmpeg.

    Args:
        video_path: Path to input video file
        output_path: Path for output audio file
        progress_callback: Optional callback for progress updates (receives progress messages)
        cancel_token: Optional cancellation token for cooperative cancellation

    Returns:
        Path to extracted audio file

    Raises:
        FFmpegNotFoundError: If FFmpeg is not available
        FileNotFoundError: If video file doesn't exist
        AudioExtractionError: If extraction fails
        Cancelled: If cancellation was requested via cancel_token
    """
    logger.debug(
        f"extract_audio called: video_path={video_path}, output_path={output_path}"
    )

    # Check FFmpeg availability
    if not check_ffmpeg_available():
        logger.error("FFmpeg is not available on this system")
        raise FFmpegNotFoundError("FFmpeg is not available on this system")

    # Check video file exists
    video_file = Path(video_path)
    if not video_file.exists():
        logger.error(f"Video file not found: {video_path}")
        raise FileNotFoundError(f"Video file not found: {video_path}")

    logger.debug(f"Video file found: {video_file.stat().st_size} bytes")

    # Extract audio using FFmpeg
    try:
        # Get video duration for progress calculation (only if callback provided)
        total_duration = None
        if progress_callback:
            try:
                total_duration = _get_video_duration(video_path)
            except AudioExtractionError:
                pass  # Continue without progress if duration unavailable

        # Build FFmpeg command
        ffmpeg_cmd = [
            "ffmpeg",
            "-i",
            str(video_path),
            "-vn",  # No video
            "-acodec",
            "pcm_s16le",  # PCM 16-bit encoding
            "-ar",
            "16000",  # 16kHz sample rate
            "-ac",
            "1",  # Mono
            "-f",
            "wav",  # WAV output format with header
        ]
        logger.debug(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")

        # Add progress reporting if callback provided
        if progress_callback:
            ffmpeg_cmd.extend(["-progress", "pipe:1"])

        ffmpeg_cmd.append(str(output_path))

        # Run FFmpeg with progress reporting
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # Parse progress output if callback provided
        if progress_callback and total_duration:
            _parse_ffmpeg_progress(
                process.stdout,
                progress_callback,
                total_duration,
                "Extracting audio",
                process,
                cancel_token,
            )
        elif cancel_token:
            # Check for cancellation periodically if no progress callback
            _check_cancel_periodically(process, cancel_token)

        # Wait for process to complete (timeout: 30 minutes for large files)
        try:
            _, stderr = process.communicate(timeout=1800)
        except subprocess.TimeoutExpired as e:
            logger.error("FFmpeg extraction timed out after 30 minutes")
            process.kill()
            process.wait()
            raise AudioExtractionError(
                "FFmpeg extraction timed out after 30 minutes"
            ) from e

        if process.returncode != 0:
            error_msg = stderr if stderr else "Unknown error"
            logger.error(f"FFmpeg extraction failed: {error_msg}")
            raise AudioExtractionError(f"FFmpeg extraction failed: {error_msg}")

        logger.debug(f"Audio extraction successful: {output_path}")
        return str(output_path)

    except subprocess.SubprocessError as e:
        logger.error(f"Audio extraction subprocess error: {str(e)}")
        raise AudioExtractionError(f"Audio extraction failed: {str(e)}") from e
