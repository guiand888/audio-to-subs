"""Tests for configuration file parser.

Tests ConfigParser for reading and validating .audio-to-subs.yaml files.
"""
import tempfile
from pathlib import Path

import pytest
import yaml

from src.config_parser import ConfigParser, ConfigError


@pytest.fixture
def temp_config_dir():
    """Create temporary directory for config files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestConfigParser:
    """Tests for ConfigParser class."""

    def test_init_file_not_found(self):
        """Test initialization fails when config file doesn't exist."""
        with pytest.raises(ConfigError, match="Config file not found"):
            ConfigParser("/nonexistent/path/config.yaml")

    def test_init_invalid_yaml(self, temp_config_dir):
        """Test initialization fails with invalid YAML syntax."""
        config_file = temp_config_dir / "bad.yaml"
        config_file.write_text("invalid: yaml: content:")

        with pytest.raises(ConfigError, match="Invalid YAML"):
            ConfigParser(str(config_file))

    def test_init_valid_config(self, temp_config_dir):
        """Test initialization with valid config file."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "jobs": [
                    {"input": "video.mp4", "output": "video.srt"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))
        assert parser.config_path == config_file

    def test_get_defaults_empty_config(self, temp_config_dir):
        """Test get_defaults with no defaults section."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"jobs": []}))

        parser = ConfigParser(str(config_file))
        defaults = parser.get_defaults()

        assert defaults["format"] == "srt"

    def test_get_defaults_with_format(self, temp_config_dir):
        """Test get_defaults returns custom format."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "defaults": {"format": "vtt"},
                "jobs": []
            })
        )

        parser = ConfigParser(str(config_file))
        defaults = parser.get_defaults()

        assert defaults["format"] == "vtt"

    def test_get_jobs_no_jobs_section(self, temp_config_dir):
        """Test get_jobs raises error when jobs section missing."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(yaml.dump({}))

        parser = ConfigParser(str(config_file))

        with pytest.raises(ConfigError, match="No jobs defined"):
            parser.get_jobs()

    def test_get_jobs_empty_jobs(self, temp_config_dir):
        """Test get_jobs raises error when jobs list is empty."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"jobs": []}))

        parser = ConfigParser(str(config_file))

        with pytest.raises(ConfigError, match="No jobs defined"):
            parser.get_jobs()

    def test_get_jobs_single_job(self, temp_config_dir):
        """Test get_jobs returns single job."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "jobs": [
                    {"input": "video.mp4", "output": "video.srt"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))
        jobs = parser.get_jobs()

        assert len(jobs) == 1
        assert jobs[0]["input"] == "video.mp4"
        assert jobs[0]["output"] == "video.srt"
        assert jobs[0]["format"] == "srt"  # default

    def test_get_jobs_multiple_jobs(self, temp_config_dir):
        """Test get_jobs returns multiple jobs."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "jobs": [
                    {"input": "video1.mp4", "output": "video1.srt"},
                    {"input": "video2.mkv", "output": "video2.vtt", "format": "vtt"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))
        jobs = parser.get_jobs()

        assert len(jobs) == 2
        assert jobs[0]["format"] == "srt"
        assert jobs[1]["format"] == "vtt"

    def test_get_jobs_missing_input(self, temp_config_dir):
        """Test get_jobs raises error when input is missing."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "jobs": [
                    {"output": "video.srt"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))

        with pytest.raises(ConfigError, match="missing required field: input"):
            parser.get_jobs()

    def test_get_jobs_missing_output(self, temp_config_dir):
        """Test get_jobs raises error when output is missing."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "jobs": [
                    {"input": "video.mp4"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))

        with pytest.raises(ConfigError, match="missing required field: output"):
            parser.get_jobs()

    def test_get_jobs_invalid_format(self, temp_config_dir):
        """Test get_jobs raises error with unsupported format."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "jobs": [
                    {"input": "video.mp4", "output": "video.srt", "format": "invalid"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))

        with pytest.raises(ConfigError, match="unsupported format"):
            parser.get_jobs()

    def test_get_jobs_format_override(self, temp_config_dir):
        """Test job format overrides defaults."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "defaults": {"format": "srt"},
                "jobs": [
                    {"input": "video.mp4", "output": "video.vtt", "format": "vtt"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))
        jobs = parser.get_jobs()

        assert jobs[0]["format"] == "vtt"

    def test_get_jobs_non_dict_job(self, temp_config_dir):
        """Test get_jobs raises error when job is not a dict."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"jobs": ["not a dict"]}))

        parser = ConfigParser(str(config_file))

        with pytest.raises(ConfigError, match="is not a dictionary"):
            parser.get_jobs()

    def test_supported_formats(self):
        """Test SUPPORTED_FORMATS contains expected formats."""
        assert "srt" in ConfigParser.SUPPORTED_FORMATS
        assert "vtt" in ConfigParser.SUPPORTED_FORMATS
        assert "webvtt" in ConfigParser.SUPPORTED_FORMATS
        assert "sbv" in ConfigParser.SUPPORTED_FORMATS

    def test_validate_returns_true(self, temp_config_dir):
        """Test validate returns True for valid config."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "jobs": [
                    {"input": "video.mp4", "output": "video.srt"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))
        assert parser.validate() is True

    def test_validate_raises_on_invalid(self, temp_config_dir):
        """Test validate raises error for invalid config."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(yaml.dump({}))

        parser = ConfigParser(str(config_file))

        with pytest.raises(ConfigError):
            parser.validate()


@pytest.mark.integration
class TestConfigParserRealWorld:
    """Integration tests with realistic config scenarios."""

    def test_batch_processing_config(self, temp_config_dir):
        """Test realistic batch processing configuration."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "defaults": {"format": "srt"},
                "jobs": [
                    {"input": "videos/meeting.mp4", "output": "subtitles/meeting.srt"},
                    {"input": "videos/presentation.mkv", "output": "subtitles/presentation.vtt", "format": "vtt"},
                    {"input": "videos/tutorial.avi", "output": "subtitles/tutorial.sbv", "format": "sbv"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))
        jobs = parser.get_jobs()

        assert len(jobs) == 3
        assert jobs[0]["format"] == "srt"
        assert jobs[1]["format"] == "vtt"
        assert jobs[2]["format"] == "sbv"

    def test_config_with_paths(self, temp_config_dir):
        """Test config with relative and absolute paths."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({
                "jobs": [
                    {"input": "./videos/local.mp4", "output": "./subtitles/local.srt"},
                    {"input": "/absolute/path/video.mp4", "output": "/absolute/output/video.srt"}
                ]
            })
        )

        parser = ConfigParser(str(config_file))
        jobs = parser.get_jobs()

        assert jobs[0]["input"] == "./videos/local.mp4"
        assert jobs[1]["input"] == "/absolute/path/video.mp4"
