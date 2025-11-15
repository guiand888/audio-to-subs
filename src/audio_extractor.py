"""Audio extraction from video files using FFmpeg."""
import subprocess
from pathlib import Path


def check_ffmpeg_available() -> bool:
    """Check if FFmpeg is available on the system.
    
    Returns:
        True if FFmpeg is available, False otherwise.
    """
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
