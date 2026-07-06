"""Shared FFmpeg/ffprobe subprocess helpers.

Used by both audio_extractor.py (video -> audio) and audio_splitter.py
(audio -> segments): availability check, ffprobe duration probing, FFmpeg
process termination, and progress-output parsing.
"""

import logging
import re
import subprocess
import time
from typing import Callable, Optional

from audio_to_subs.core.cancel import Cancelled, CancelToken

logger = logging.getLogger(__name__)

# Cache for FFmpeg availability check (checked once at startup, not per-call)
_ffmpeg_available_cached: Optional[bool] = None


def check_ffmpeg_available() -> bool:
    """Check if FFmpeg is available on the system.

    Result is cached after first check to avoid repeated subprocess calls.

    Returns:
        True if FFmpeg is available, False otherwise.
    """
    global _ffmpeg_available_cached

    if _ffmpeg_available_cached is not None:
        return _ffmpeg_available_cached

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        _ffmpeg_available_cached = result.returncode == 0
    except FileNotFoundError:
        _ffmpeg_available_cached = False
    except subprocess.TimeoutExpired:
        logger.warning("FFmpeg availability check timed out after 10 seconds")
        _ffmpeg_available_cached = False

    return _ffmpeg_available_cached


def probe_duration(media_path: str) -> float:
    """Get duration of a media file in seconds via ffprobe.

    Args:
        media_path: Path to video or audio file

    Returns:
        Duration in seconds

    Raises:
        subprocess.CalledProcessError: If ffprobe fails
        subprocess.TimeoutExpired: If ffprobe times out
        ValueError: If ffprobe output cannot be parsed as a float

    Callers are expected to catch these and re-raise as their own
    module-specific error type (AudioExtractionError / AudioSplitterError).
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            media_path,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return float(result.stdout.strip())


def terminate_ffmpeg(process: subprocess.Popen) -> None:
    """Terminate FFmpeg process and wait for cleanup.

    Args:
        process: The FFmpeg subprocess to terminate
    """
    logger.info("Terminating FFmpeg process due to cancellation")
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        logger.warning("FFmpeg did not terminate in time, killing")
        process.kill()
        process.wait()


def parse_ffmpeg_progress(  # noqa: C901
    stdout,
    progress_callback: Callable[[str], None],
    total_duration: float,
    operation_name: str,
    process: subprocess.Popen,
    cancel_token: Optional[CancelToken] = None,
) -> None:
    """Parse FFmpeg progress output and call callback with formatted progress.

    Args:
        stdout: FFmpeg stdout stream with progress output
        progress_callback: Callback to receive progress messages
        total_duration: Total duration in seconds
        operation_name: Name of the operation (e.g., "Extracting audio")
        process: The subprocess to terminate if cancelled
        cancel_token: Optional cancellation token to check periodically
    """
    pattern_us = re.compile(r"^out_time_us=(\d+)$")
    pattern_time = re.compile(r"^out_time=([0-9:.]+)$")

    def parse_timecode(tc: str) -> float:
        h, m, s = tc.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    last_percent = -1
    try:
        for raw_line in stdout or []:
            # Check for cancellation before processing each line
            if cancel_token is not None:
                try:
                    cancel_token.check()
                except Cancelled:
                    terminate_ffmpeg(process)
                    raise

            line = raw_line.strip()
            time_s: Optional[float] = None

            m_us = pattern_us.match(line)
            if m_us:
                us = int(m_us.group(1))
                # FFmpeg reports microseconds here
                time_s = us / 1_000_000.0
            else:
                m_time = pattern_time.match(line)
                if m_time:
                    time_s = parse_timecode(m_time.group(1))

            if time_s is not None and total_duration and total_duration > 0:
                percentage = min(100.0, (time_s / total_duration) * 100.0)
                # Throttle duplicate percentages
                if int(percentage) != last_percent:
                    last_percent = int(percentage)
                    progress_callback(
                        f"{operation_name}: {time_s:.1f} / {total_duration:.1f}s ({percentage:.1f}%)"
                    )

            if line == "progress=end" and total_duration:
                progress_callback(
                    f"{operation_name}: {total_duration:.1f} / {total_duration:.1f}s (100.0%)"
                )
                break
    except Cancelled:
        raise


def check_cancel_periodically(
    process: subprocess.Popen, cancel_token: CancelToken
) -> None:
    """Check for cancellation periodically while process runs.

    Args:
        process: The subprocess to monitor
        cancel_token: The cancellation token to check
    """
    while process.poll() is None:
        try:
            cancel_token.check()
        except Cancelled:
            terminate_ffmpeg(process)
            raise
        time.sleep(0.1)
