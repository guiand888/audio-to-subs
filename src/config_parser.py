"""Configuration file parser for batch processing.

Supports .audio-to-subs.yaml configuration files for defining batch jobs.
"""
from pathlib import Path
from typing import List, Dict, Optional, Any
import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid."""
    pass


class ConfigParser:
    """Parse and validate .audio-to-subs.yaml configuration files."""

    SUPPORTED_FORMATS = ["srt", "vtt", "webvtt", "sbv"]

    def __init__(self, config_path: str):
        """Initialize config parser.

        Args:
            config_path: Path to .audio-to-subs.yaml file

        Raises:
            ConfigError: If config file not found or invalid YAML
        """
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")

        try:
            with open(self.config_path) as f:
                self.config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in {config_path}: {str(e)}")
        except Exception as e:
            raise ConfigError(f"Failed to read config: {str(e)}")

    def get_defaults(self) -> Dict[str, Any]:
        """Get default settings for all jobs.

        Returns:
            Dict with default configuration (format, temp_dir, etc.)
        """
        defaults = self.config.get("defaults", {})
        if "format" not in defaults:
            defaults["format"] = "srt"
        return defaults

    def get_jobs(self) -> List[Dict[str, str]]:
        """Get list of jobs to process.

        Returns:
            List of job dicts with input, output, and optional format

        Raises:
            ConfigError: If jobs are missing or invalid
        """
        jobs = self.config.get("jobs", [])

        if not jobs:
            raise ConfigError("No jobs defined in configuration")

        # Validate and normalize each job
        validated_jobs = []
        for idx, job in enumerate(jobs):
            if not isinstance(job, dict):
                raise ConfigError(f"Job {idx} is not a dictionary")

            if "input" not in job:
                raise ConfigError(f"Job {idx} missing required field: input")

            if "output" not in job:
                raise ConfigError(f"Job {idx} missing required field: output")

            # Normalize with defaults
            defaults = self.get_defaults()
            normalized_job = {
                "input": job["input"],
                "output": job["output"],
                "format": job.get("format", defaults.get("format", "srt")),
            }

            # Validate format
            if normalized_job["format"] not in self.SUPPORTED_FORMATS:
                raise ConfigError(
                    f"Job {idx}: unsupported format '{normalized_job['format']}'. "
                    f"Must be one of: {', '.join(self.SUPPORTED_FORMATS)}"
                )

            validated_jobs.append(normalized_job)

        return validated_jobs

    def validate(self) -> bool:
        """Validate entire configuration.

        Returns:
            True if configuration is valid

        Raises:
            ConfigError: If configuration is invalid
        """
        # Ensure we have jobs
        self.get_jobs()
        return True
