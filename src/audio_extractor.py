"""Audio extraction from video files using FFmpeg."""
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional


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
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        raise AudioExtractionError(f"Failed to get video duration: {str(e)}") from e


def extract_audio(
    video_path: str,
    output_path: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Extract audio from video file using FFmpeg.
    
    Args:
        video_path: Path to input video file
        output_path: Path for output audio file
        progress_callback: Optional callback for progress updates (receives progress messages)
        
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
        # Get video duration for progress calculation (only if callback provided)
        total_duration = None
        if progress_callback:
            try:
                total_duration = _get_video_duration(video_path)
            except AudioExtractionError:
                pass  # Continue without progress if duration unavailable
        
        # Build FFmpeg command
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # PCM 16-bit encoding
            '-ar', '16000',  # 16kHz sample rate
            '-ac', '1',  # Mono
        ]
        
        # Add progress reporting if callback provided
        if progress_callback:
            ffmpeg_cmd.extend(['-progress', 'pipe:1'])
        
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
                process.stdout, progress_callback, total_duration, "Extracting audio"
            )
        
        # Wait for process to complete
        _, stderr = process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr if stderr else "Unknown error"
            raise AudioExtractionError(f"FFmpeg extraction failed: {error_msg}")
        
        return str(output_path)
        
    except subprocess.SubprocessError as e:
        raise AudioExtractionError(f"Audio extraction failed: {str(e)}") from e


def _parse_ffmpeg_progress(
    stdout,
    progress_callback: Callable[[str], None],
    total_duration: float,
    operation_name: str,
) -> None:
    """Parse FFmpeg progress output and call callback with formatted progress.
    
    Args:
        stdout: FFmpeg stdout stream with progress output
        progress_callback: Callback to receive progress messages
        total_duration: Total duration in seconds
        operation_name: Name of the operation (e.g., "Extracting audio")
    """
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
