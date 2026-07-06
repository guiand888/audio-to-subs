"""Command-line interface for audio-to-subs.

Provides CLI tools for converting video audio to subtitles using Mistral AI transcription.
Supports single video processing and batch processing via configuration files.
"""

import logging
import os
import sys
from pathlib import Path

import click

from audio_to_subs.core.config_parser import ConfigError, ConfigParser
from audio_to_subs.core.logging_config import configure_logging
from audio_to_subs.core.pipeline import Pipeline, PipelineError

logger = logging.getLogger(__name__)

__version__ = "0.1.0"

#: Supported subtitle output formats
SUPPORTED_FORMATS = ["srt", "vtt", "webvtt", "sbv"]

#: Exit codes
EXIT_CONFIG_ERROR = 1
EXIT_VALIDATION_ERROR = 1
EXIT_OUTPUT_DIR_ERROR = 2
EXIT_PROCESSING_ERROR = 1
EXIT_UNEXPECTED_ERROR = 1

#: Percentage range bounds
MIN_PERCENTAGE = 0
MAX_PERCENTAGE = 100


def _validate_output_directory(output_path: str) -> None:
    """Validate that output directory is writable.

    Args:
        output_path: Path to output file

    Raises:
        click.ClickException: If directory is not writable
    """
    output_file = Path(output_path)
    output_dir = output_file.parent

    # Create directory if it doesn't exist
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise click.ClickException(
            f"Cannot create output directory '{output_dir}': {str(e)}"
        ) from e

    # Check if directory is writable
    if not os.access(output_dir, os.W_OK):
        raise click.ClickException(f"Output directory is not writable: {output_dir}")

    logger.debug(f"Output directory is writable: {output_dir}")


def _validate_config_and_mode(
    config_path: str | None, input_path: str | None, output_path: str | None
) -> None:
    """Validate that configuration mode and single-video mode are mutually exclusive.

    Args:
        config_path: Configuration file path
        input_path: Input video file path
        output_path: Output subtitle file path

    Raises:
        click.ClickException: If both config and input/output are provided
    """
    if config_path and (input_path or output_path):
        click.echo("Error: --config cannot be used with --input or --output", err=True)
        sys.exit(EXIT_CONFIG_ERROR)


def _validate_single_video_args(
    input_path: str | None, output_path: str | None, api_key: str | None
) -> None:
    """Validate that all required single-video arguments are provided.

    Args:
        input_path: Input video file path
        output_path: Output subtitle file path
        api_key: Mistral AI API key

    Raises:
        SystemExit: If any required argument is missing or invalid
    """
    if not input_path:
        click.echo("Error: --input is required", err=True)
        sys.exit(EXIT_VALIDATION_ERROR)

    if not output_path:
        click.echo("Error: --output is required", err=True)
        sys.exit(EXIT_VALIDATION_ERROR)

    if not api_key:
        click.echo(
            "Error: API key required. Provide with --api-key or set MISTRAL_API_KEY",
            err=True,
        )
        sys.exit(EXIT_VALIDATION_ERROR)

    # Check input file exists
    if not Path(input_path).exists():
        click.echo(f"Error: Input file not found: {input_path}", err=True)
        sys.exit(EXIT_VALIDATION_ERROR)


def _process_single_video(
    input_path: str,
    output_path: str,
    output_format: str,
    api_key: str,
    model: str,
    language: str | None,
    progress: bool,
) -> None:
    """Process a single video file and generate subtitles.

    Args:
        input_path: Input video file path
        output_path: Output subtitle file path
        output_format: Subtitle output format
        api_key: Mistral AI API key
        model: Transcription model to use
        language: Language code for transcription
        progress: Show detailed progress messages

    Raises:
        SystemExit: On processing error
    """
    # Validate output directory is writable
    try:
        _validate_output_directory(output_path)
    except click.ClickException as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(EXIT_OUTPUT_DIR_ERROR)

    try:
        # Create progress callback
        def progress_callback(message: str, percentage: int | None = None) -> None:
            """Display progress message to user.

            Args:
                message: Progress status message
                percentage: Optional percentage (0-100)
            """
            if progress:
                click.echo(f"[*] {message}")

        # Initialize pipeline
        pipeline = Pipeline(
            api_key=api_key,
            progress_callback=progress_callback,
            transcription_model=model,
            language=language,
            verbose_progress=progress,
        )

        # Process video
        click.echo(f"Processing: {input_path}")
        result = pipeline.process_video(
            input_path, output_path, output_format=output_format
        )

        click.echo(f"\n✓ Success! Subtitles saved to: {result}")

    except PipelineError as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(EXIT_PROCESSING_ERROR)
    except Exception as e:
        click.echo(f"Error: Unexpected error - {str(e)}", err=True)
        sys.exit(EXIT_UNEXPECTED_ERROR)


@click.command()
@click.option(
    "-i",
    "--input",
    "input_path",
    required=False,
    type=click.Path(exists=True),
    help="Input video file path",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=False,
    type=click.Path(),
    help="Output subtitle file path",
)
@click.option(
    "-f",
    "--format",
    "output_format",
    type=click.Choice(SUPPORTED_FORMATS),
    default="srt",
    help="Output subtitle format (default: srt)",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True),
    help="Configuration file for batch processing (.audio-to-subs.yaml)",
)
@click.option(
    "--api-key",
    "api_key",
    default=None,
    envvar="MISTRAL_API_KEY",
    help="Mistral AI API key (or set MISTRAL_API_KEY environment variable)",
)
@click.option(
    "--model",
    "model",
    default="voxtral-mini-latest",
    help="Transcription model to use (default: voxtral-mini-latest)",
)
@click.option(
    "--language",
    "language",
    default=None,
    help="Language code for transcription (e.g., en, fr). Default: auto-detect",
)
@click.option(
    "--progress",
    is_flag=True,
    help="Show detailed progress (file upload, transcription segments)",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable debug logging for detailed output",
)
@click.option("--version", is_flag=True, help="Show version")
def main(
    input_path: str | None,
    output_path: str | None,
    output_format: str,
    config_path: str | None,
    api_key: str | None,
    model: str,
    language: str | None,
    progress: bool,
    verbose: bool,
    version: bool,
) -> None:
    """Convert video audio to subtitles using Mistral AI transcription.

    Supports single video processing or batch processing via configuration file.

    \b
    Single video usage:
      audio-to-subs -i video.mp4 -o output.srt --api-key YOUR_KEY
      audio-to-subs -i video.mp4 -o output.vtt --format vtt

    Batch processing:
      audio-to-subs --config .audio-to-subs.yaml

    Or set MISTRAL_API_KEY environment variable:
      export MISTRAL_API_KEY=your_key
      audio-to-subs -i video.mp4 -o output.srt
    """
    # Configure logging early
    configure_logging(verbose=verbose)

    if version:
        click.echo(f"audio-to-subs v{__version__}")
        return

    logger.debug(f"CLI invoked with verbose={verbose}, progress={progress}")

    # Validate that config mode and single-video mode are mutually exclusive
    _validate_config_and_mode(config_path, input_path, output_path)

    # Batch processing mode
    if config_path:
        logger.debug(f"Batch mode: config_path={config_path}")
        _process_batch(config_path, api_key, model, progress, verbose)
        return

    # Single video processing
    _validate_single_video_args(input_path, output_path, api_key)
    _process_single_video(
        input_path, output_path, output_format, api_key, model, language, progress
    )


def _process_batch(
    config_path: str,
    api_key: str | None,
    model: str,
    progress: bool,
    verbose: bool = False,
) -> None:
    """Process multiple videos from configuration file.

    Args:
        config_path: Path to .audio-to-subs.yaml configuration file
        api_key: Mistral AI API key
        model: Transcription model to use
        progress: Show detailed progress messages
        verbose: Enable debug logging

    Raises:
        SystemExit: On error
    """
    logger.debug(f"_process_batch called with config_path={config_path}")
    if not api_key:
        click.echo(
            "Error: API key required. Provide with --api-key or set MISTRAL_API_KEY",
            err=True,
        )
        sys.exit(EXIT_VALIDATION_ERROR)

    try:
        # Parse configuration
        config = ConfigParser(config_path)
        config.validate()
        jobs = config.get_jobs()

        # Create progress callback
        def progress_callback(message: str, percentage: int | None = None) -> None:
            if progress:
                click.echo(f"[*] {message}")

        # Initialize pipeline
        pipeline = Pipeline(
            api_key=api_key,
            progress_callback=progress_callback,
            transcription_model=model,
            language=None,
        )

        # Process all jobs
        click.echo(f"Processing {len(jobs)} video(s)...\n")
        results = pipeline.process_batch(jobs)

        # Show results
        click.echo("\n✓ Batch processing complete!")
        for input_path, output_path in results.items():
            click.echo(f"  {input_path} → {output_path}")

    except ConfigError as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)
    except PipelineError as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(EXIT_PROCESSING_ERROR)
    except Exception as e:
        click.echo(f"Error: Unexpected error - {str(e)}", err=True)
        sys.exit(EXIT_UNEXPECTED_ERROR)


if __name__ == "__main__":
    main()
