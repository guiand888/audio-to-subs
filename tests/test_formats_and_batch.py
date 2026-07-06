"""Tests for output formats and batch processing.

Tests subtitle generation in SRT, VTT, WebVTT, and SBV formats.
Tests batch processing pipeline.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_to_subs.core.pipeline import Pipeline, PipelineError
from audio_to_subs.core.subtitle_generator import (
    SubtitleFormatError,
    SubtitleGenerator,
    format_timestamp_sbv,
    format_timestamp_srt,
    format_timestamp_vtt,
)

# Test data fixtures
SAMPLE_SEGMENTS: list[dict[str, Any]] = [
    {"start": 1.5, "end": 5.0, "text": "First subtitle"},
    {"start": 5.5, "end": 10.0, "text": "Second subtitle"},
    {"start": 10.5, "end": 15.0, "text": "Third subtitle with\nmultiple lines"},
]


class TestTimestampFormatters:
    """Tests for timestamp formatting functions."""

    @pytest.mark.parametrize(
        "seconds,expected_srt,expected_vtt,expected_sbv",
        [
            (0, "00:00:00,000", "00:00:00.000", "0:00:00,000"),
            (1.5, "00:00:01,500", "00:00:01.500", "0:00:01,500"),
            (65.5, "00:01:05,500", "00:01:05.500", "0:01:05,500"),
            (3661.5, "01:01:01,500", "01:01:01.500", "1:01:01,500"),
            (36661.999, "10:11:01,999", "10:11:01.999", "10:11:01,999"),
        ],
    )
    def test_format_timestamps(self, seconds, expected_srt, expected_vtt, expected_sbv):
        """Test timestamp formatting for all formats."""
        assert format_timestamp_srt(seconds) == expected_srt
        assert format_timestamp_vtt(seconds) == expected_vtt
        assert format_timestamp_sbv(seconds) == expected_sbv

    def test_vtt_uses_dot_separator(self):
        """Test VTT uses dot instead of comma for milliseconds."""
        srt = format_timestamp_srt(1.5)
        vtt = format_timestamp_vtt(1.5)
        assert "," in srt
        assert "." in vtt
        assert srt.replace(",", ".") == vtt


class TestSubtitleGenerator:
    """Tests for SubtitleGenerator class."""

    @pytest.fixture
    def generator(self):
        """Create SubtitleGenerator instance."""
        return SubtitleGenerator()

    @pytest.fixture
    def temp_output_dir(self, tmp_path):
        """Create temporary directory for output files."""
        return tmp_path

    def test_supported_formats(self, generator):
        """Test SUPPORTED_FORMATS contains all formats."""
        assert "srt" in generator.SUPPORTED_FORMATS
        assert "vtt" in generator.SUPPORTED_FORMATS
        assert "webvtt" in generator.SUPPORTED_FORMATS
        assert "sbv" in generator.SUPPORTED_FORMATS

    @pytest.mark.parametrize(
        "format_name,expected_ext,expected_content,separator",
        [
            ("srt", ".srt", "00:00:01,500 --> 00:00:05,000", ","),
            ("vtt", ".vtt", "00:00:01.500 --> 00:00:05.000", "."),
            ("webvtt", ".vtt", "WEBVTT", "."),
            ("sbv", ".sbv", "0:00:01,500", ","),
        ],
    )
    def test_generate_formats(
        self,
        generator,
        temp_output_dir,
        format_name,
        expected_ext,
        expected_content,
        separator,
    ):
        """Test subtitle generation for all formats."""
        output_path = str(temp_output_dir / f"output{expected_ext}")
        result = generator.generate(SAMPLE_SEGMENTS, output_path, format_name)

        assert result == output_path
        assert Path(output_path).exists()
        content = Path(output_path).read_text()
        assert expected_content in content
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
        segments = [{"start": 0, "end": 5, "text": "First line\nSecond line"}]
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
        with (
            patch("audio_to_subs.core.pipeline.extract_audio"),
            patch("audio_to_subs.core.pipeline.TranscriptionClient"),
            patch("audio_to_subs.core.pipeline.SubtitleGenerator"),
        ):
            pipeline = Pipeline(api_key="test-key")
            return pipeline

    def test_process_batch_single_job(self, pipeline_with_mock):
        """Test batch processing with single job."""
        jobs = [{"input": "video1.mp4", "output": "video1.srt", "format": "srt"}]

        with patch.object(
            pipeline_with_mock, "process_video", return_value="video1.srt"
        ):
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
            side_effect=["video1.srt", "video2.vtt", "video3.sbv"],
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

        with patch.object(
            pipeline_with_mock, "process_video", return_value="output.srt"
        ):
            pipeline_with_mock.process_batch(jobs)

        # Should be called for each job
        assert callback.call_count >= 2

    def test_process_batch_continues_after_error(self, pipeline_with_mock):
        """Batch processing logs a failed job and continues with the rest
        (B25: does not abort the whole batch on the first failure)."""
        jobs = [
            {"input": "bad_video.mp4", "output": "output1.srt", "format": "srt"},
            {"input": "good_video.mp4", "output": "output2.srt", "format": "srt"},
        ]

        with patch.object(
            pipeline_with_mock,
            "process_video",
            side_effect=[PipelineError("Test error"), "output2.srt"],
        ):
            results = pipeline_with_mock.process_batch(jobs)

        assert "bad_video.mp4" not in results
        assert results["good_video.mp4"] == "output2.srt"

    def test_process_batch_respects_format(self, pipeline_with_mock):
        """Test batch processing passes format to process_video."""
        jobs = [{"input": "video1.mp4", "output": "video1.vtt", "format": "vtt"}]

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

    def test_all_formats_generate_same_content(self, tmp_path):
        """Test all formats contain the same text content."""
        generator = SubtitleGenerator()

        srt_path = tmp_path / "output.srt"
        vtt_path = tmp_path / "output.vtt"
        sbv_path = tmp_path / "output.sbv"

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
