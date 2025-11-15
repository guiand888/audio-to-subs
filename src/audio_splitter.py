"""Audio file splitting for transcription.

Handles audio files exceeding Mistral's 15-minute limit by splitting
into segments and processing independently.
"""
import subprocess
from pathlib import Path
from typing import Any

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


def split_audio(audio_path: str, output_dir: str, max_length: int = MAX_AUDIO_LENGTH) -> list[str]:
    """Split audio file into segments.

    Args:
        audio_path: Path to input audio file
        output_dir: Directory to save split files
        max_length: Maximum length of each segment in seconds

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

        segments = []
        segment_count = 0
        start_time = 0

        while start_time < duration:
            segment_count += 1
            end_time = min(start_time + max_length, duration)
            duration_str = end_time - start_time

            output_file = output_dir_path / f"segment_{segment_count:03d}.wav"

            subprocess.run(
                [
                    "ffmpeg",
                    "-i", audio_path,
                    "-ss", str(start_time),
                    "-to", str(end_time),
                    "-c", "copy",
                    "-y",
                    str(output_file)
                ],
                capture_output=True,
                check=True
            )

            segments.append(str(output_file))
            start_time = end_time - OVERLAP  # Overlap for context

        return segments

    except subprocess.CalledProcessError as e:
        raise AudioSplitterError(f"FFmpeg error during splitting: {e.stderr.decode()}") from e
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
