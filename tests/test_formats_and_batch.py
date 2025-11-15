"""Tests for output formats and batch processing.

Tests subtitle generation in SRT, VTT, WebVTT, and SBV formats.
Tests batch processing pipeline.
"""
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.subtitle_generator import (
    SubtitleGenerator,
    format_timestamp_srt,
    format_timestamp_vtt,
    format_timestamp_sbv,
    SubtitleFormatError,
)
from src.pipeline import Pipeline, PipelineError


# Test data fixtures
SAMPLE_SEGMENTS: list[dict[str, Any]] = [
    {"start": 1.5, "end": 5.0, "text": "First subtitle"},
    {"start": 5.5, "end": 10.0, "text": "Second subtitle"},
    {"start": 10.5, "end": 15.0, "text": "Third subtitle with\nmultiple lines"},
]


class TestTimestampFormatters:
    """Tests for timestamp formatting functions."""

    class TestSRTTimestamp:
        """Tests for SRT timestamp format (HH:MM:SS,mmm)."""

        def test_format_zero_seconds(self):
            """Test formatting 0 seconds."""
            assert format_timestamp_srt(0) == "00:00:00,000"

        def test_format_milliseconds(self):
            """Test formatting with milliseconds."""
            assert format_timestamp_srt(1.5) == "00:00:01,500"

        def test_format_minutes(self):
            """Test formatting with minutes."""
            assert format_timestamp_srt(65.5) == "00:01:05,500"

        def test_format_hours(self):
            """Test formatting with hours."""
            assert format_timestamp_srt(3661.5) == "01:01:01,500"

        def test_format_large_value(self):
            """Test formatting large time values."""
            assert format_timestamp_srt(36661.999) == "10:11:01,999"

    class TestVTTTimestamp:
        """Tests for VTT timestamp format (HH:MM:SS.mmm)."""

        def test_format_zero_seconds(self):
            """Test formatting 0 seconds."""
            assert format_timestamp_vtt(0) == "00:00:00.000"

        def test_format_milliseconds(self):
            """Test formatting with milliseconds."""
            assert format_timestamp_vtt(1.5) == "00:00:01.500"

        def test_format_uses_dot_separator(self):
            """Test VTT uses dot instead of comma for milliseconds."""
            srt = format_timestamp_srt(1.5)
            vtt = format_timestamp_vtt(1.5)
            assert "," in srt
            assert "." in vtt
            assert srt.replace(",", ".") == vtt

    class TestSBVTimestamp:
        """Tests for SBV timestamp format (H:MM:SS,mmm)."""

        def test_format_zero_seconds(self):
            """Test formatting 0 seconds."""
            assert format_timestamp_sbv(0) == "0:00:00,000"

        def test_format_no_leading_hour_zero(self):
            """Test SBV doesn't use leading zero for hours."""
            sbv = format_timestamp_sbv(3661.5)
            srt = format_timestamp_srt(3661.5)
            # SRT: 01:01:01,500
            # SBV: 1:01:01,500
            assert sbv == "1:01:01,500"
            assert srt == "01:01:01,500"


class TestSubtitleGenerator:
    """Tests for SubtitleGenerator class."""

    @pytest.fixture
    def generator(self):
        """Create SubtitleGenerator instance."""
        return SubtitleGenerator()

    @pytest.fixture
    def temp_output_dir(self):
        """Create temporary directory for output files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_supported_formats(self, generator):
        """Test SUPPORTED_FORMATS contains all formats."""
        assert "srt" in generator.SUPPORTED_FORMATS
        assert "vtt" in generator.SUPPORTED_FORMATS
        assert "webvtt" in generator.SUPPORTED_FORMATS
        assert "sbv" in generator.SUPPORTED_FORMATS

    def test_generate_srt(self, generator, temp_output_dir):
        """Test SRT file generation."""
        output_path = str(temp_output_dir / "output.srt")
        result = generator.generate(SAMPLE_SEGMENTS, output_path, "srt")

        assert result == output_path
        assert Path(output_path).exists()

        content = Path(output_path).read_text()
        assert "First subtitle" in content
        assert "00:00:01,500 --> 00:00:05,000" in content
        assert "1" in content  # subtitle number

    def test_generate_vtt(self, generator, temp_output_dir):
        """Test VTT file generation."""
        output_path = str(temp_output_dir / "output.vtt")
        result = generator.generate(SAMPLE_SEGMENTS, output_path, "vtt")

        assert result == output_path
        content = Path(output_path).read_text()
        assert "WEBVTT" in content
        assert "00:00:01.500 --> 00:00:05.000" in content  # dot separator
        assert "First subtitle" in content

    def test_generate_webvtt(self, generator, temp_output_dir):
        """Test WebVTT format (same as vtt)."""
        output_path = str(temp_output_dir / "output.vtt")
        generator.generate(SAMPLE_SEGMENTS, output_path, "webvtt")

        content = Path(output_path).read_text()
        assert "WEBVTT" in content

    def test_generate_sbv(self, generator, temp_output_dir):
        """Test SBV file generation."""
        output_path = str(temp_output_dir / "output.sbv")
        generator.generate(SAMPLE_SEGMENTS, output_path, "sbv")

        content = Path(output_path).read_text()
        assert "0:00:01,500" in content  # SBV format
        assert "First subtitle" in content

    def test_generate_unsupported_format(self, generator, temp_output_dir):
        """Test error on unsupported format."""
        output_path = str(temp_output_dir / "output.txt")

        with pytest.raises(SubtitleFormatError, match="Unsupported format"):
            generator.generate(SAMPLE_SEGMENTS, output_path, "unsupported")

    def test_generate_invalid_segment_missing_start(self, generator, temp_output_dir):
        """Test error on missing start time."""
        invalid_segments = [{"end": 5.0, "text": "No start"}]
        output_path = str(temp_output_dir / "output.srt")

        with pytest.raises(SubtitleFormatError, match="Missing required field"):
            generator.generate(invalid_segments, output_path, "srt")

    def test_generate_invalid_segment_negative_time(self, generator, temp_output_dir):
        """Test error on negative time."""
        invalid_segments = [{"start": -1.0, "end": 5.0, "text": "Negative time"}]
        output_path = str(temp_output_dir / "output.srt")

        with pytest.raises(SubtitleFormatError, match="Invalid timecode"):
            generator.generate(invalid_segments, output_path, "srt")

    def test_generate_multiline_text(self, generator, temp_output_dir):
        """Test generation with multiline subtitle text."""
        segments = [
            {"start": 0, "end": 5, "text": "First line\nSecond line"}
        ]
        output_path = str(temp_output_dir / "output.srt")
        generator.generate(segments, output_path, "srt")

        content = Path(output_path).read_text()
        assert "First line" in content
        assert "Second line" in content


class TestBatchProcessing:
    """Tests for batch processing in Pipeline."""

    @pytest.fixture
    def pipeline_with_mock(self):
        """Create Pipeline with mocked dependencies."""
        with patch("src.pipeline.extract_audio"), \
             patch("src.pipeline.TranscriptionClient"), \
             patch("src.pipeline.SubtitleGenerator"):
            pipeline = Pipeline(api_key="test-key")
            return pipeline

    def test_process_batch_single_job(self, pipeline_with_mock):
        """Test batch processing with single job."""
        jobs = [
            {"input": "video1.mp4", "output": "video1.srt", "format": "srt"}
        ]

        with patch.object(pipeline_with_mock, "process_video", return_value="video1.srt"):
            results = pipeline_with_mock.process_batch(jobs)

        assert len(results) == 1
        assert "video1.mp4" in results

    def test_process_batch_multiple_jobs(self, pipeline_with_mock):
        """Test batch processing with multiple jobs."""
        jobs = [
            {"input": "video1.mp4", "output": "video1.srt", "format": "srt"},
            {"input": "video2.mkv", "output": "video2.vtt", "format": "vtt"},
            {"input": "video3.avi", "output": "video3.sbv", "format": "sbv"},
        ]

        with patch.object(
            pipeline_with_mock,
            "process_video",
            side_effect=["video1.srt", "video2.vtt", "video3.sbv"]
        ):
            results = pipeline_with_mock.process_batch(jobs)

        assert len(results) == 3
        assert results["video1.mp4"] == "video1.srt"
        assert results["video2.mkv"] == "video2.vtt"
        assert results["video3.avi"] == "video3.sbv"

    def test_process_batch_with_progress_callback(self, pipeline_with_mock):
        """Test batch processing calls progress callback."""
        callback = MagicMock()
        pipeline_with_mock.progress_callback = callback

        jobs = [
            {"input": "video1.mp4", "output": "video1.srt", "format": "srt"},
            {"input": "video2.mkv", "output": "video2.vtt", "format": "vtt"},
        ]

        with patch.object(pipeline_with_mock, "process_video", return_value="output.srt"):
            pipeline_with_mock.process_batch(jobs)

        # Should be called for each job
        assert callback.call_count >= 2

    def test_process_batch_propagates_errors(self, pipeline_with_mock):
        """Test batch processing propagates errors from process_video."""
        jobs = [
            {"input": "bad_video.mp4", "output": "output.srt", "format": "srt"}
        ]

        with patch.object(
            pipeline_with_mock,
            "process_video",
            side_effect=PipelineError("Test error")
        ):
            with pytest.raises(PipelineError):
                pipeline_with_mock.process_batch(jobs)

    def test_process_batch_respects_format(self, pipeline_with_mock):
        """Test batch processing passes format to process_video."""
        jobs = [
            {"input": "video1.mp4", "output": "video1.vtt", "format": "vtt"}
        ]

        with patch.object(pipeline_with_mock, "process_video") as mock_process:
            mock_process.return_value = "video1.vtt"
            pipeline_with_mock.process_batch(jobs)

            # Check that format was passed
            mock_process.assert_called_once()
            args, kwargs = mock_process.call_args
            assert kwargs.get("output_format") == "vtt" or args[2] == "vtt"


@pytest.mark.integration
class TestFormatConversions:
    """Integration tests for format conversions."""

    def test_all_formats_generate_same_content(self):
        """Test all formats contain the same text content."""
        generator = SubtitleGenerator()

        with tempfile.TemporaryDirectory() as tmpdir:
            srt_path = Path(tmpdir) / "output.srt"
            vtt_path = Path(tmpdir) / "output.vtt"
            sbv_path = Path(tmpdir) / "output.sbv"

            generator.generate(SAMPLE_SEGMENTS, str(srt_path), "srt")
            generator.generate(SAMPLE_SEGMENTS, str(vtt_path), "vtt")
            generator.generate(SAMPLE_SEGMENTS, str(sbv_path), "sbv")

            srt_text = srt_path.read_text()
            vtt_text = vtt_path.read_text()
            sbv_text = sbv_path.read_text()

            # All should contain the subtitle text
            for text in ["First subtitle", "Second subtitle", "Third subtitle"]:
                assert text in srt_text
                assert text in vtt_text
                assert text in sbv_text
