"""Generate subtitle files in multiple formats from transcription segments.

Supported formats:
- SRT (SubRip): .srt files
- VTT (WebVTT): .vtt files
- WebVTT: Full .vtt format with metadata
- SBV (YouTube): .sbv files
"""
from pathlib import Path
from typing import List, Dict, Literal


class SubtitleFormatError(Exception):
    """Raised when subtitle format is invalid."""
    pass


def format_timestamp_srt(seconds: float) -> str:
    """Format seconds into SRT timestamp format (HH:MM:SS,mmm).
    
    Args:
        seconds: Time in seconds as float
        
    Returns:
        Formatted SRT timestamp string
    """
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """Format seconds into VTT timestamp format (HH:MM:SS.mmm).
    
    Args:
        seconds: Time in seconds as float
        
    Returns:
        Formatted VTT timestamp string
    """
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def format_timestamp_sbv(seconds: float) -> str:
    """Format seconds into SBV timestamp format (H:MM:SS,mmm).
    
    Args:
        seconds: Time in seconds as float
        
    Returns:
        Formatted SBV timestamp string
    """
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    return f"{hours}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


class SubtitleGenerator:
    """Generate subtitle files in multiple formats from transcription segments."""

    SUPPORTED_FORMATS = ["srt", "vtt", "webvtt", "sbv"]

    def generate(self, segments: List[Dict], output_path: str, output_format: str = "srt") -> str:
        """Generate subtitle file in specified format.
        
        Args:
            segments: List of dicts with 'start', 'end', and 'text' keys
            output_path: Path to write subtitle file
            output_format: Format to generate (srt, vtt, webvtt, sbv)
            
        Returns:
            Path to generated subtitle file
            
        Raises:
            SubtitleFormatError: If format is unsupported or data is invalid
        """
        if output_format not in self.SUPPORTED_FORMATS:
            raise SubtitleFormatError(
                f"Unsupported format: {output_format}. "
                f"Must be one of: {', '.join(self.SUPPORTED_FORMATS)}"
            )
        
        if output_format == "srt":
            return self.generate_srt(segments, output_path)
        elif output_format in ["vtt", "webvtt"]:
            return self.generate_vtt(segments, output_path)
        elif output_format == "sbv":
            return self.generate_sbv(segments, output_path)

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
            start_time = format_timestamp_srt(segment["start"])
            end_time = format_timestamp_srt(segment["end"])
            text = segment["text"]
            
            srt_lines.append(str(index))
            srt_lines.append(f"{start_time} --> {end_time}")
            srt_lines.append(text)
            srt_lines.append("")  # Blank line between subtitles
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(srt_lines))
        
        return str(output_path)

    def generate_vtt(self, segments: List[Dict], output_path: str) -> str:
        """Generate VTT file from transcription segments.
        
        Args:
            segments: List of dicts with 'start', 'end', and 'text' keys
            output_path: Path to write VTT file
            
        Returns:
            Path to generated VTT file
            
        Raises:
            SubtitleFormatError: If format is invalid or required fields missing
        """
        # Validate segments
        for segment in segments:
            self._validate_segment(segment)
        
        # Generate VTT content
        vtt_lines = ["WEBVTT", ""]
        for segment in segments:
            start_time = format_timestamp_vtt(segment["start"])
            end_time = format_timestamp_vtt(segment["end"])
            text = segment["text"]
            
            vtt_lines.append(f"{start_time} --> {end_time}")
            vtt_lines.append(text)
            vtt_lines.append("")  # Blank line between subtitles
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(vtt_lines))
        
        return str(output_path)

    def generate_sbv(self, segments: List[Dict], output_path: str) -> str:
        """Generate SBV file from transcription segments.
        
        Args:
            segments: List of dicts with 'start', 'end', and 'text' keys
            output_path: Path to write SBV file
            
        Returns:
            Path to generated SBV file
            
        Raises:
            SubtitleFormatError: If format is invalid or required fields missing
        """
        # Validate segments
        for segment in segments:
            self._validate_segment(segment)
        
        # Generate SBV content
        sbv_lines = []
        for segment in segments:
            start_time = format_timestamp_sbv(segment["start"])
            end_time = format_timestamp_sbv(segment["end"])
            text = segment["text"]
            
            sbv_lines.append(start_time)
            sbv_lines.append(end_time)
            sbv_lines.append(text)
            sbv_lines.append("")  # Blank line between subtitles
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(sbv_lines))
        
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
