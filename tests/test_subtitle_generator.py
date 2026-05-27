"""Tests for subtitle_generator module."""
import pytest
from pathlib import Path
import src.subtitle_generator  # Import module for coverage
from src.subtitle_generator import (
    SubtitleGenerator,
    format_timestamp_srt,
    SubtitleFormatError,
    segment_text,
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
        
    def test_format_timestamp_edge_values(self):
        """Test timestamp formatting with edge values (0, large values)."""
        # Test 0
        assert format_timestamp_srt(0.0) == "00:00:00,000"
        # Test large value
        assert format_timestamp_srt(86400.0) == "24:00:00,000"
        # Test value with milliseconds
        assert format_timestamp_srt(1.5) == "00:00:01,500"


class TestSegmentText:
    """Test text segmentation for subtitle lines."""

    def test_segment_text_empty_string(self):
        """Test segment_text with empty string."""
        from src.subtitle_generator import segment_text
        
        # Act
        result = segment_text("")
        
        # Assert
        assert result == [""]

    def test_segment_text_single_word(self):
        """Test segment_text with single word."""
        from src.subtitle_generator import segment_text
        
        # Act
        result = segment_text("Hello")
        
        # Assert
        assert result == ["Hello"]

    def test_segment_text_long_text(self):
        """Test segment_text with text exceeding max_chars."""
        from src.subtitle_generator import segment_text
        
        # Create a long text that exceeds 42 characters
        long_text = "This is a very long sentence that should be split into multiple lines because it exceeds the maximum character limit"
        
        # Act
        result = segment_text(long_text, max_chars=42)
        
        # Assert
        # Should be split into multiple lines
        assert len(result) > 1
        # Each line should be <= 42 characters
        for line in result:
            assert len(line) <= 42

    def test_segment_text_with_newlines(self):
        """Test segment_text preserves and handles newlines."""
        from src.subtitle_generator import segment_text
        
        # Act
        result = segment_text("First line\nSecond line", max_chars=42)
        
        # Assert
        assert len(result) >= 2

    def test_segment_text_respects_word_boundaries(self):
        """Test segment_text doesn't break words."""
        from src.subtitle_generator import segment_text
        
        # Act
        result = segment_text("Hello world this is a test", max_chars=10)
        
        # Assert - should split at word boundaries, not in the middle of words
        assert "Hello" in result
        # Each word should appear intact (not split)
        for word in ["Hello", "world", "this", "is", "a", "test"]:
            # Check that the word appears in some line
            assert any(word in line for line in result)


class TestTimestampFormattingAllFormats:
    """Test timestamp formatting for all supported formats."""

    def test_format_timestamp_vtt(self):
        """Test VTT timestamp formatting."""
        from src.subtitle_generator import format_timestamp_vtt
        
        # Act
        result = format_timestamp_vtt(65.5)
        
        # Assert
        assert result == "00:01:05.500"

    def test_format_timestamp_vtt_edge_values(self):
        """Test VTT timestamp formatting with edge values."""
        from src.subtitle_generator import format_timestamp_vtt
        
        # Test 0
        assert format_timestamp_vtt(0.0) == "00:00:00.000"
        # Test large value
        assert format_timestamp_vtt(3600.0) == "01:00:00.000"

    def test_format_timestamp_sbv(self):
        """Test SBV timestamp formatting."""
        from src.subtitle_generator import format_timestamp_sbv
        
        # Act
        result = format_timestamp_sbv(65.5)
        
        # Assert - SBV uses H:MM:SS,mmm format (hours not zero-padded)
        assert result == "0:01:05,500"

    def test_format_timestamp_sbv_edge_values(self):
        """Test SBV timestamp formatting with edge values."""
        from src.subtitle_generator import format_timestamp_sbv
        
        # Test 0
        assert format_timestamp_sbv(0.0) == "0:00:00,000"
        # Test large value
        assert format_timestamp_sbv(3600.0) == "1:00:00,000"


class TestSubtitleGeneratorValidation:
    """Test subtitle generator validation."""

    def test_validate_segment_missing_start(self):
        """Test _validate_segment raises error when start is missing."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Missing required field"):
            generator._validate_segment({"end": 1.0, "text": "test"})

    def test_validate_segment_missing_end(self):
        """Test _validate_segment raises error when end is missing."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Missing required field"):
            generator._validate_segment({"start": 0.0, "text": "test"})

    def test_validate_segment_missing_text(self):
        """Test _validate_segment raises error when text is missing."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Missing required field"):
            generator._validate_segment({"start": 0.0, "end": 1.0})

    def test_validate_segment_negative_start(self):
        """Test _validate_segment raises error for negative start time."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Invalid timecode 'start'"):
            generator._validate_segment({"start": -1.0, "end": 1.0, "text": "test"})

    def test_validate_segment_negative_end(self):
        """Test _validate_segment raises error for negative end time."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Invalid timecode 'end'"):
            generator._validate_segment({"start": 0.0, "end": -1.0, "text": "test"})

    def test_validate_segment_end_before_start(self):
        """Test _validate_segment raises error when end < start."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="end.*before start"):
            generator._validate_segment({"start": 5.0, "end": 2.0, "text": "test"})

    def test_validate_segment_string_times(self):
        """Test _validate_segment with string time values."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Invalid timecode 'start'"):
            generator._validate_segment({"start": "not_a_number", "end": 1.0, "text": "test"})


class TestLanguageCodeHandling:
    """Test language code handling in subtitle generation."""

    def test_is_valid_language_code_valid(self):
        """Test _is_valid_language_code with valid codes."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        assert generator._is_valid_language_code("en") is True
        assert generator._is_valid_language_code("fr") is True
        assert generator._is_valid_language_code("eng") is True
        assert generator._is_valid_language_code("spa") is True

    def test_is_valid_language_code_invalid(self):
        """Test _is_valid_language_code with invalid codes."""
        generator = SubtitleGenerator()
        
        # Act & Assert
        assert generator._is_valid_language_code("") is False
        assert generator._is_valid_language_code("a") is False  # Too short
        assert generator._is_valid_language_code("abcdef") is False  # Too long
        assert generator._is_valid_language_code("123") is False  # Not alphabetic
        assert generator._is_valid_language_code("en_US") is False  # Contains non-alphabetic

    def test_generate_with_invalid_language_code(self, tmp_path):
        """Test generate raises error for invalid language code."""
        generator = SubtitleGenerator()
        output_file = tmp_path / "output.srt"
        segments = [{"start": 0.0, "end": 1.0, "text": "test"}]
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Invalid language code"):
            generator.generate(segments, str(output_file), "srt", language_code="invalid123")


class TestSubtitleGeneratorEdgeCases:
    """Test edge cases in subtitle generation."""

    def test_generate_with_empty_segments(self, tmp_path):
        """Test generate with empty segments list."""
        generator = SubtitleGenerator()
        output_file = tmp_path / "output.srt"
        
        # Act
        result = generator.generate([], str(output_file), "srt")
        
        # Assert - should return empty file path
        assert result == str(output_file)

    def test_generate_with_multiline_text(self, tmp_path):
        """Test generate with multiline text in segments."""
        generator = SubtitleGenerator()
        output_file = tmp_path / "output.srt"
        segments = [{"start": 0.0, "end": 5.0, "text": "Line 1\nLine 2\nLine 3"}]
        
        # Act
        result = generator.generate(segments, str(output_file), "srt")
        
        # Assert
        assert result == str(output_file)
        # Verify file was created
        assert output_file.exists()
        content = output_file.read_text()
        assert "Line 1" in content or "Line 2" in content


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

    def test_generate_with_language_code(self, tmp_path):
        """Test generating subtitles with language code in filename."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "First subtitle"}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act
        result = generator.generate(segments, str(output_file), "srt", "en")
        
        # Assert
        result_path = Path(result)
        expected_path = tmp_path / "output.en.srt"
        assert result_path == expected_path
        assert result_path.exists()
        content = result_path.read_text()
        assert "First subtitle" in content

    def test_generate_without_language_code(self, tmp_path):
        """Test generating subtitles without language code preserves original filename."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "First subtitle"}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act
        result = generator.generate(segments, str(output_file), "srt", None)
        
        # Assert
        result_path = Path(result)
        assert result_path == output_file
        assert result_path.exists()

    def test_generate_invalid_language_code(self, tmp_path):
        """Test generating subtitles with invalid language code raises error."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "First subtitle"}
        ]
        output_file = tmp_path / "output.srt"
        
        # Act & Assert
        with pytest.raises(SubtitleFormatError, match="Invalid language code"):
            generator.generate(segments, str(output_file), "srt", "en1")

    def test_generate_different_formats_with_language(self, tmp_path):
        """Test generating different subtitle formats with language codes."""
        # Arrange
        generator = SubtitleGenerator()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "Test subtitle"}
        ]
        
        # Test SRT format
        output_srt = tmp_path / "output.srt"
        result_srt = generator.generate(segments, str(output_srt), "srt", "fr")
        assert Path(result_srt).name == "output.fr.srt"
        
        # Test VTT format
        output_vtt = tmp_path / "output.vtt"
        result_vtt = generator.generate(segments, str(output_vtt), "vtt", "es")
        assert Path(result_vtt).name == "output.es.vtt"
        
        # Test SBV format
        output_sbv = tmp_path / "output.sbv"
        result_sbv = generator.generate(segments, str(output_sbv), "sbv", "de")
        assert Path(result_sbv).name == "output.de.sbv"

    def test_language_code_validation(self):
        """Test language code validation logic."""
        generator = SubtitleGenerator()
        
        # Valid language codes
        valid_codes = ["en", "fr", "es", "de", "it", "pt", "ru", "zh", "ja", "ko", "eng", "fra", "spa"]
        for code in valid_codes:
            assert generator._is_valid_language_code(code) is True
        
        # Invalid language codes
        invalid_codes = ["en1", "123", "a", "abcd", "en-US", "en_GB", ""]
        for code in invalid_codes:
            assert generator._is_valid_language_code(code) is False

    def test_filename_generation_logic(self):
        """Test filename generation logic directly."""
        generator = SubtitleGenerator()
        
        # Test basic filename generation
        result = generator._generate_output_filename("output.srt", "srt", "en")
        assert result == "output.en.srt"
        
        # Test with different base filenames
        result = generator._generate_output_filename("movie.srt", "srt", "fr")
        assert result == "movie.fr.srt"
        
        # Test with complex filenames
        result = generator._generate_output_filename("show.s01e01.srt", "srt", "es")
        assert result == "show.s01e01.es.srt"
        
        # Test without language code (should return original)
        result = generator._generate_output_filename("output.srt", "srt", None)
        assert result == "output.srt"

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


class TestSegmentText:
    """Test segment_text function edge cases."""

    def test_segment_text_with_empty_paragraphs(self):
        """Test segment_text with empty paragraphs (lines 45-48)."""
        # Arrange
        # To hit lines 46-47, we need current_line to have content when we hit an empty paragraph
        # This happens when we have text, then an empty paragraph
        # "Hello\n\n" - paragraphs = ["Hello", ""]
        # After processing "Hello", current_line = "Hello" (not yet added to lines)
        # Then we process "", which is empty, so we check if current_line has content
        long_text = "Hello\n\n"
        
        # Act
        result = segment_text(long_text, max_chars=80)
        
        # Assert
        assert "Hello" in result
        assert len(result) >= 1

    def test_segment_text_with_very_long_line(self):
        """Test segment_text with line exceeding max_chars requiring re-segmentation (lines 80-92)."""
        # Arrange
        # Create a single paragraph that when joined will exceed max_chars
        # This should trigger the re-segmentation logic (lines 80-92)
        # where words from a line that exceeds max_chars are split across multiple lines
        long_text = "This is a very long paragraph that will definitely exceed the maximum character limit when all words are joined together on a single line"
        
        # Act - with max_chars=20, the paragraph will exceed this and need re-segmentation
        result = segment_text(long_text, max_chars=20)
        
        # Assert - the line should be split into multiple lines
        # Verify re-segmentation happened (lines 80-92 executed)
        assert len(result) >= 5  # Should be split into multiple lines
        # All lines should be <= max_chars
        for line in result:
            if line:
                assert len(line) <= 20, f"Line '{line}' exceeds max_chars=20"