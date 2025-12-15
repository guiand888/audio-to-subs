"""Tests for subtitle_generator module."""
import pytest
from pathlib import Path
from src.subtitle_generator import (
    SubtitleGenerator,
    format_timestamp_srt,
    SubtitleFormatError
)


class TestTimestampFormatting:
    """Test timestamp formatting for SRT."""

    def test_format_timestamp_zero(self):
        """Test formatting timestamp at 0 seconds."""
        # Act
        result = format_timestamp_srt(0.0)
        
        # Assert
        assert result == "00:00:00,000"

    def test_format_timestamp_basic(self):
        """Test formatting basic timestamp."""
        # Act
        result = format_timestamp_srt(65.5)
        
        # Assert
        assert result == "00:01:05,500"

    def test_format_timestamp_with_hours(self):
        """Test formatting timestamp with hours."""
        # Act
        result = format_timestamp_srt(3661.123)
        
        # Assert
        assert result == "01:01:01,123"

    def test_format_timestamp_large_value(self):
        """Test formatting large timestamp."""
        # Act
        result = format_timestamp_srt(36000.999)
        
        # Assert
        assert result == "10:00:00,999"

    def test_format_timestamp_rounds_milliseconds(self):
        """Test that milliseconds are rounded correctly."""
        # Act
        result = format_timestamp_srt(5.9999)
        
        # Assert
        assert result == "00:00:05,999"


class TestSubtitleGenerator:
    """Test SRT subtitle generation."""

    def test_generate_srt_single_segment(self, tmp_path):
        """Test generating SRT with single segment."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "First subtitle"}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act
        result = generator.generate_srt(segments, str(output_file))
        
        # Assert
        assert result == str(output_file)
        assert output_file.exists()
        content = output_file.read_text()
        assert "1" in content
        assert "00:00:00,000 --> 00:00:02,500" in content
        assert "First subtitle" in content

    def test_generate_srt_multiple_segments(self, tmp_path):
        """Test generating SRT with multiple segments."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "First"},
            {"start": 2.5, "end": 5.0, "text": "Second"},
            {"start": 5.0, "end": 8.5, "text": "Third"}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act
        generator.generate_srt(segments, str(output_file))
        
        # Assert
        content = output_file.read_text()
        lines = content.strip().split('\n')
        # Should have 3 blocks of (index + timecode + text + blank)
        assert len([line for line in lines if line.strip()]) == 9  # 3*(1+1+1)
        assert "1\n00:00:00,000 --> 00:00:02,500\nFirst" in content
        assert "2\n00:00:02,500 --> 00:00:05,000\nSecond" in content
        assert "3\n00:00:05,000 --> 00:00:08,500\nThird" in content

    def test_generate_srt_empty_segments(self, tmp_path):
        """Test generating SRT with empty segments list."""
        # Arrange
        generator = SubtitleGenerator()
        segments = []
        output_file = tmp_path / "output.srt"
        
        # Act
        generator.generate_srt(segments, str(output_file))
        
        # Assert
        assert output_file.exists()
        content = output_file.read_text()
        assert content.strip() == ""

    def test_generate_srt_missing_fields(self, tmp_path):
        """Test generating SRT raises error with missing required fields."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5}  # Missing 'text'
        ]
        output_file = tmp_path / "output.srt"
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Missing required field"):
            generator.generate_srt(segments, str(output_file))

    def test_generate_srt_invalid_timecode(self, tmp_path):
        """Test generating SRT raises error with invalid timecode."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": -1.0, "end": 2.5, "text": "Invalid"}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Invalid timecode"):
            generator.generate_srt(segments, str(output_file))

    def test_generate_srt_multiline_text(self, tmp_path):
        """Test generating SRT with multiline subtitle text."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "Line 1\nLine 2"}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act
        generator.generate_srt(segments, str(output_file))
        
        # Assert
        content = output_file.read_text()
        assert "Line 1" in content
        assert "Line 2" in content

    def test_generate_srt_long_text_segmentation(self, tmp_path):
        """Test generating SRT with long text that requires segmentation."""
        # Arrange
        generator = SubtitleGenerator()
        long_text = "This is a very long subtitle text that should be segmented into multiple lines to comply with subtitle width constraints and best practices for readability on screen."
        segments = [
            {"start": 0.0, "end": 5.0, "text": long_text}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act
        generator.generate_srt(segments, str(output_file))
        
        # Assert
        content = output_file.read_text()
        lines = [line for line in content.split('\n') if line.strip() and not line[0].isdigit() and '-->' not in line]
        
        # Should have multiple lines due to segmentation
        assert len(lines) > 1
        
        # Each line should be within reasonable length (max 42 chars + some tolerance)
        for line in lines:
            assert len(line) <= 50, f"Line exceeds maximum length: '{line}' ({len(line)} chars)"
        
        # All original text should be preserved
        assert long_text.replace(' ', '') in ''.join(lines).replace(' ', '').replace('\n', '')

    def test_segment_text_function(self):
        """Test the segment_text function directly."""
        from src.subtitle_generator import segment_text
        
        # Test basic segmentation
        long_text = "This is a very long sentence that should be split into multiple lines for better readability."
        result = segment_text(long_text)
        
        assert len(result) > 1
        for line in result:
            assert len(line) <= 42
        
        # Test with existing newlines
        multiline_text = "First line\nSecond line that is quite long and should be segmented"
        result = segment_text(multiline_text)
        assert len(result) >= 2
        
        # Test empty text
        result = segment_text("")
        assert result == [""]
        
        # Test short text
        short_text = "Short text"
        result = segment_text(short_text)
        assert result == [short_text]

    def test_generate_srt_write_to_file(self, tmp_path):
        """Test that SRT file is written with correct permissions."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "Test"}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act
        generator.generate_srt(segments, str(output_file))
        
        # Assert
        assert output_file.is_file()
        assert output_file.stat().st_size > 0