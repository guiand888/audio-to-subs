"""Audio file splitting for transcription.

Handles audio files exceeding Mistral's 15-minute limit by splitting
into segments and processing independently.
"""

import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional

from audio_to_subs.core.cancel import Cancelled, CancelToken
from audio_to_subs.core.ffmpeg_utils import (
    check_cancel_periodically as _check_cancel_periodically,
)
from audio_to_subs.core.ffmpeg_utils import (
    parse_ffmpeg_progress as _parse_ffmpeg_progress,
)
from audio_to_subs.core.ffmpeg_utils import (
    probe_duration,
)

logger = logging.getLogger(__name__)

MAX_AUDIO_LENGTH = 900  # 15 minutes in seconds
OVERLAP = 2  # 2-second overlap to preserve context at boundaries


class AudioSplitterError(Exception):
    """Raised when audio splitting fails."""

    pass


def get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds.

    Args:
        audio_path: Path to audio file

    Returns:
        Duration in seconds

    Raises:
        AudioSplitterError: If duration cannot be determined
    """
    try:
        return probe_duration(audio_path)
    except (subprocess.CalledProcessError, ValueError) as e:
        raise AudioSplitterError(f"Failed to get audio duration: {str(e)}") from e


def split_audio(
    audio_path: str,
    output_dir: str,
    max_length: int = MAX_AUDIO_LENGTH,
    progress_callback: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[CancelToken] = None,
) -> list[str]:
    """Split audio file into segments.

    Args:
        audio_path: Path to input audio file
        output_dir: Directory to save split files
        max_length: Maximum length of each segment in seconds
        progress_callback: Optional callback for progress updates per segment
        cancel_token: Optional cancellation token for cooperative cancellation

    Returns:
        List of paths to split audio files in order

    Raises:
        AudioSplitterError: If splitting fails
        Cancelled: If cancellation was requested via cancel_token
    """
    try:
        duration = get_audio_duration(audio_path)

        if duration <= max_length:
            return [audio_path]  # No splitting needed

        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        # Pre-compute segment boundaries to know total segment count
        segments_bounds: list[tuple[float, float]] = []
        start_time = 0.0
        while start_time < duration:
            end_time = min(start_time + max_length, duration)
            segments_bounds.append((start_time, end_time))
            if end_time >= duration:
                break
            start_time = end_time - OVERLAP  # Overlap for context

        total_segments = len(segments_bounds)
        segments: list[str] = []

        for idx, (start_time, end_time) in enumerate(segments_bounds, start=1):
            # Check for cancellation before each segment
            if cancel_token is not None:
                cancel_token.check()

            output_file = output_dir_path / f"segment_{idx:03d}.wav"

            ffmpeg_cmd = [
                "ffmpeg",
                "-i",
                audio_path,
                "-ss",
                str(start_time),
                "-to",
                str(end_time),
                "-c",
                "copy",
                "-y",
            ]
            if progress_callback:
                ffmpeg_cmd.extend(["-progress", "pipe:1"])
            ffmpeg_cmd.append(str(output_file))

            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            if progress_callback:
                seg_duration = max(0.0, end_time - start_time)
                _parse_ffmpeg_progress(
                    process.stdout,
                    progress_callback,
                    seg_duration,
                    f"Splitting segment {idx}/{total_segments}",
                    process,
                    cancel_token,
                )
            elif cancel_token:
                _check_cancel_periodically(process, cancel_token)

            # Wait for segment to complete (timeout: 30 minutes per segment)
            try:
                _, stderr = process.communicate(timeout=1800)
            except subprocess.TimeoutExpired as e:
                logger.error(
                    f"FFmpeg splitting timed out for segment {idx} after 30 minutes"
                )
                process.kill()
                process.wait()
                raise AudioSplitterError(
                    f"FFmpeg splitting timed out for segment {idx} after 30 minutes"
                ) from e

            if process.returncode != 0:
                error_msg = stderr if stderr else "Unknown error"
                raise AudioSplitterError(f"FFmpeg error during splitting: {error_msg}")

            segments.append(str(output_file))

        return segments

    except Cancelled:
        raise
    except subprocess.CalledProcessError as e:
        raise AudioSplitterError(
            f"FFmpeg error during splitting: {e.stderr.decode()}"
        ) from e
    except Exception as e:
        raise AudioSplitterError(f"Audio splitting failed: {str(e)}") from e


def needs_splitting(audio_path: str, max_length: int = MAX_AUDIO_LENGTH) -> bool:
    """Check if audio file needs splitting.

    Args:
        audio_path: Path to audio file
        max_length: Maximum allowed length in seconds

    Returns:
        True if file exceeds max_length, False otherwise

    Raises:
        AudioSplitterError: If duration cannot be determined
    """
    duration = get_audio_duration(audio_path)
    return duration > max_length
