"""Audio file splitting for transcription.

Handles audio files exceeding Mistral's 15-minute limit by splitting
into segments and processing independently.
"""
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

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
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1:nokey=1",
                audio_path
            ],
            capture_output=True,
            text=True,
            check=True
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        raise AudioSplitterError(f"Failed to get audio duration: {str(e)}") from e


def split_audio(
    audio_path: str,
    output_dir: str,
    max_length: int = MAX_AUDIO_LENGTH,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> list[str]:
    """Split audio file into segments.

    Args:
        audio_path: Path to input audio file
        output_dir: Directory to save split files
        max_length: Maximum length of each segment in seconds
        progress_callback: Optional callback for progress updates per segment

    Returns:
        List of paths to split audio files in order

    Raises:
        AudioSplitterError: If splitting fails
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
            output_file = output_dir_path / f"segment_{idx:03d}.wav"

            ffmpeg_cmd = [
                "ffmpeg",
                "-i", audio_path,
                "-ss", str(start_time),
                "-to", str(end_time),
                "-c", "copy",
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
                )

            _, stderr = process.communicate()
            if process.returncode != 0:
                error_msg = stderr if stderr else "Unknown error"
                raise AudioSplitterError(
                    f"FFmpeg error during splitting: {error_msg}"
                )

            segments.append(str(output_file))

        return segments

    except subprocess.CalledProcessError as e:
        raise AudioSplitterError(f"FFmpeg error during splitting: {e.stderr.decode()}") from e
    except Exception as e:
        raise AudioSplitterError(f"Audio splitting failed: {str(e)}") from e


def _parse_ffmpeg_progress(
    stdout,
    progress_callback: Callable[[str], None],
    total_duration: float,
    operation_name: str,
) -> None:
    """Parse FFmpeg progress output and call callback with formatted progress."""
    pattern_us = re.compile(r'^out_time_us=(\d+)$')
    pattern_time = re.compile(r'^out_time=([0-9:.]+)$')

    def parse_timecode(tc: str) -> float:
        h, m, s = tc.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    last_percent = -1
    for raw_line in stdout or []:
        line = raw_line.strip()
        time_s: Optional[float] = None

        m_us = pattern_us.match(line)
        if m_us:
            us = int(m_us.group(1))
            time_s = us / 1_000_000.0
        else:
            m_time = pattern_time.match(line)
            if m_time:
                time_s = parse_timecode(m_time.group(1))

        if time_s is not None and total_duration > 0:
            percentage = min(100.0, (time_s / total_duration) * 100.0)
            if int(percentage) != last_percent:
                last_percent = int(percentage)
                progress_callback(
                    f"{operation_name}: {time_s:.1f} / {total_duration:.1f}s ({percentage:.1f}%)"
                )

        if line == "progress=end" and total_duration > 0:
            progress_callback(
                f"{operation_name}: {total_duration:.1f} / {total_duration:.1f}s (100.0%)"
            )
            break


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
