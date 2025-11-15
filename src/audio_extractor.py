"""Audio extraction from video files using FFmpeg."""
import subprocess
from pathlib import Path


class FFmpegNotFoundError(Exception):
    """Raised when FFmpeg is not available on the system."""
    pass


class AudioExtractionError(Exception):
    """Raised when audio extraction fails."""
    pass


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


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video file using FFmpeg.
    
    Args:
        video_path: Path to input video file
        output_path: Path for output audio file
        
    Returns:
        Path to extracted audio file
        
    Raises:
        FFmpegNotFoundError: If FFmpeg is not available
        FileNotFoundError: If video file doesn't exist
        AudioExtractionError: If extraction fails
    """
    # Check FFmpeg availability
    if not check_ffmpeg_available():
        raise FFmpegNotFoundError("FFmpeg is not available on this system")
    
    # Check video file exists
    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # Extract audio using FFmpeg
    try:
        result = subprocess.run(
            [
                'ffmpeg',
                '-i', str(video_path),
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # PCM 16-bit encoding
                '-ar', '16000',  # 16kHz sample rate
                '-ac', '1',  # Mono
                str(output_path)
            ],
            capture_output=True,
            check=False
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.decode() if result.stderr else "Unknown error"
            raise AudioExtractionError(f"FFmpeg extraction failed: {error_msg}")
        
        return str(output_path)
        
    except subprocess.SubprocessError as e:
        raise AudioExtractionError(f"Audio extraction failed: {str(e)}")
