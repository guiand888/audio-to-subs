"""Generate SRT subtitle files from transcription segments."""
from pathlib import Path
from typing import List, Dict


class SubtitleFormatError(Exception):
    """Raised when subtitle format is invalid."""
    pass


def format_timestamp(seconds: float) -> str:
    """Format seconds into SRT timestamp format (HH:MM:SS,mmm).
    
    Args:
        seconds: Time in seconds as float
        
    Returns:
        Formatted timestamp string
    """
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


class SubtitleGenerator:
    """Generate SRT subtitle files from transcription segments."""

    def generate_srt(self, segments: List[Dict], output_path: str) -> str:
        """Generate SRT file from transcription segments.
        
        Args:
            segments: List of dicts with 'start', 'end', and 'text' keys
            output_path: Path to write SRT file
            
        Returns:
            Path to generated SRT file
            
        Raises:
            SubtitleFormatError: If format is invalid or required fields missing
        """
        # Validate segments
        for segment in segments:
            self._validate_segment(segment)
        
        # Generate SRT content
        srt_lines = []
        for index, segment in enumerate(segments, 1):
            start_time = format_timestamp(segment["start"])
            end_time = format_timestamp(segment["end"])
            text = segment["text"]
            
            srt_lines.append(str(index))
            srt_lines.append(f"{start_time} --> {end_time}")
            srt_lines.append(text)
            srt_lines.append("")  # Blank line between subtitles
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(srt_lines))
        
        return str(output_path)

    def _validate_segment(self, segment: Dict) -> None:
        """Validate segment has required fields and valid values.
        
        Args:
            segment: Segment dictionary to validate
            
        Raises:
            SubtitleFormatError: If validation fails
        """
        required_fields = {"start", "end", "text"}
        missing_fields = required_fields - set(segment.keys())
        
        if missing_fields:
            raise SubtitleFormatError(
                f"Missing required field: {', '.join(missing_fields)}"
            )
        
        start = segment["start"]
        end = segment["end"]
        
        # Validate timecodes
        if not isinstance(start, (int, float)) or start < 0:
            raise SubtitleFormatError(
                f"Invalid timecode 'start': {start} (must be non-negative number)"
            )
        
        if not isinstance(end, (int, float)) or end < 0:
            raise SubtitleFormatError(
                f"Invalid timecode 'end': {end} (must be non-negative number)"
            )
        
        if end < start:
            raise SubtitleFormatError(
                f"Invalid timecode range: end ({end}) before start ({start})"
            )
