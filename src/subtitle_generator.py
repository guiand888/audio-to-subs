"""Generate subtitle files in multiple formats from transcription segments.

Supported formats:
- SRT (SubRip): .srt files
- VTT (WebVTT): .vtt files
- WebVTT: Full .vtt format with metadata
- SBV (YouTube): .sbv files
"""
from pathlib import Path
from typing import Any, List


class SubtitleFormatError(Exception):
    """Raised when subtitle format is invalid."""
    pass


def segment_text(text: str, max_chars: int = 42) -> List[str]:
    """Segment text into lines with maximum character length.
    
    Args:
        text: Input text to segment
        max_chars: Maximum characters per line (default: 42)
        
    Returns:
        List of segmented text lines
        
    Note:
        - Preserves word boundaries (doesn't break words)
        - Respects existing newlines
        - Creates multiple lines as needed to stay within max_chars
        - Prefers 2 lines when possible (industry standard)
    """
    if not text:
        return [text]
    
    lines = []
    current_line = ""
    
    # Split by existing newlines first
    paragraphs = text.split('\n')
    
    for paragraph in paragraphs:
        if not paragraph.strip():
            if current_line:
                lines.append(current_line)
                current_line = ""
            continue
            
        words = paragraph.split(' ')
        
        for word in words:
            # Check if adding this word would exceed max_chars
            if current_line and len(current_line) + len(word) + 1 > max_chars:  # +1 for space
                lines.append(current_line)
                current_line = word
            else:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
        
        # If we have content and this isn't the last paragraph, add current line
        if current_line and paragraph != paragraphs[-1]:
            lines.append(current_line)
            current_line = ""
    
    # Add any remaining content
    if current_line:
        lines.append(current_line)
    
    # Ensure all lines are within the max_chars limit
    # This handles cases where the initial segmentation created lines > max_chars
    final_lines = []
    for line in lines:
        if len(line) <= max_chars:
            final_lines.append(line)
        else:
            # Re-segment this line if it exceeds max_chars
            words = line.split(' ')
            current = ""
            for word in words:
                if current and len(current) + len(word) + 1 > max_chars:
                    final_lines.append(current)
                    current = word
                else:
                    if current:
                        current += " " + word
                    else:
                        current = word
            if current:
                final_lines.append(current)
    
    return final_lines


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

    def generate(self, segments: list[dict[str, Any]], output_path: str, output_format: str = "srt") -> str:
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

    def generate_srt(self, segments: list[dict[str, Any]], output_path: str) -> str:
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
        entry_index = 1
        
        for segment in segments:
            start_time_seconds = segment["start"]
            end_time_seconds = segment["end"]
            text = segment["text"]
            
            # Apply text segmentation for maximum width constraint
            segmented_lines = segment_text(text)
            
            # Calculate total duration
            total_duration = end_time_seconds - start_time_seconds
            
            # Split into pages of max 2 lines per subtitle entry (industry standard)
            num_pages = (len(segmented_lines) + 1) // 2  # Ceiling division
            duration_per_page = total_duration / num_pages if num_pages > 0 else total_duration
            
            for page_index, page_start in enumerate(range(0, len(segmented_lines), 2)):
                page_end = min(page_start + 2, len(segmented_lines))
                page_lines = segmented_lines[page_start:page_end]
                
                # Calculate proportional timestamps for this page
                page_start_time = start_time_seconds + (page_index * duration_per_page)
                page_end_time = start_time_seconds + ((page_index + 1) * duration_per_page)
                
                # Ensure the last page ends at the original end time
                if page_index == num_pages - 1:
                    page_end_time = end_time_seconds
                
                page_start_str = format_timestamp_srt(page_start_time)
                page_end_str = format_timestamp_srt(page_end_time)
                
                srt_lines.append(str(entry_index))
                srt_lines.append(f"{page_start_str} --> {page_end_str}")
                srt_lines.extend(page_lines)
                srt_lines.append("")  # Blank line between subtitles
                
                entry_index += 1
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(srt_lines))
        
        return str(output_path)

    def generate_vtt(self, segments: list[dict[str, Any]], output_path: str) -> str:
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
            start_time_seconds = segment["start"]
            end_time_seconds = segment["end"]
            text = segment["text"]
            
            # Apply text segmentation for maximum width constraint
            segmented_lines = segment_text(text)
            
            # Calculate total duration
            total_duration = end_time_seconds - start_time_seconds
            
            # Split into pages of max 2 lines per subtitle entry (industry standard)
            num_pages = (len(segmented_lines) + 1) // 2  # Ceiling division
            duration_per_page = total_duration / num_pages if num_pages > 0 else total_duration
            
            for page_index, page_start in enumerate(range(0, len(segmented_lines), 2)):
                page_end = min(page_start + 2, len(segmented_lines))
                page_lines = segmented_lines[page_start:page_end]
                
                # Calculate proportional timestamps for this page
                page_start_time = start_time_seconds + (page_index * duration_per_page)
                page_end_time = start_time_seconds + ((page_index + 1) * duration_per_page)
                
                # Ensure the last page ends at the original end time
                if page_index == num_pages - 1:
                    page_end_time = end_time_seconds
                
                page_start_str = format_timestamp_vtt(page_start_time)
                page_end_str = format_timestamp_vtt(page_end_time)
                
                vtt_lines.append(f"{page_start_str} --> {page_end_str}")
                vtt_lines.extend(page_lines)
                vtt_lines.append("")  # Blank line between subtitles
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(vtt_lines))
        
        return str(output_path)

    def generate_sbv(self, segments: list[dict[str, Any]], output_path: str) -> str:
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
            start_time_seconds = segment["start"]
            end_time_seconds = segment["end"]
            text = segment["text"]
            
            # Apply text segmentation for maximum width constraint
            segmented_lines = segment_text(text)
            
            # Calculate total duration
            total_duration = end_time_seconds - start_time_seconds
            
            # Split into pages of max 2 lines per subtitle entry (industry standard)
            num_pages = (len(segmented_lines) + 1) // 2  # Ceiling division
            duration_per_page = total_duration / num_pages if num_pages > 0 else total_duration
            
            for page_index, page_start in enumerate(range(0, len(segmented_lines), 2)):
                page_end = min(page_start + 2, len(segmented_lines))
                page_lines = segmented_lines[page_start:page_end]
                
                # Calculate proportional timestamps for this page
                page_start_time = start_time_seconds + (page_index * duration_per_page)
                page_end_time = start_time_seconds + ((page_index + 1) * duration_per_page)
                
                # Ensure the last page ends at the original end time
                if page_index == num_pages - 1:
                    page_end_time = end_time_seconds
                
                page_start_str = format_timestamp_sbv(page_start_time)
                page_end_str = format_timestamp_sbv(page_end_time)
                
                sbv_lines.append(page_start_str)
                sbv_lines.append(page_end_str)
                sbv_lines.extend(page_lines)
                sbv_lines.append("")  # Blank line between subtitles
        
        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(sbv_lines))
        
        return str(output_path)

    def _validate_segment(self, segment: dict[str, Any]) -> None:
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
