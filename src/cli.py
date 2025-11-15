"""Command-line interface for audio-to-subs.

Provides CLI tools for converting video audio to subtitles using Mistral AI transcription.
Supports single video processing and batch processing via configuration files.
"""
import sys

import click

from src.config_parser import ConfigError, ConfigParser
from src.pipeline import Pipeline, PipelineError

__version__ = "0.1.0"

#: Supported subtitle output formats
SUPPORTED_FORMATS = ["srt", "vtt", "webvtt", "sbv"]


@click.command()
@click.option(
    '-i', '--input',
    'input_path',
    required=False,
    type=click.Path(exists=True),
    help='Input video file path'
)
@click.option(
    '-o', '--output',
    'output_path',
    required=False,
    type=click.Path(),
    help='Output subtitle file path'
)
@click.option(
    '-f', '--format',
    'output_format',
    type=click.Choice(SUPPORTED_FORMATS),
    default='srt',
    help='Output subtitle format (default: srt)'
)
@click.option(
    '--config',
    'config_path',
    type=click.Path(exists=True),
    help='Configuration file for batch processing (.audio-to-subs.yaml)'
)
@click.option(
    '--api-key',
    'api_key',
    default=None,
    envvar='MISTRAL_API_KEY',
    help='Mistral AI API key (or set MISTRAL_API_KEY environment variable)'
)
@click.option(
    '--version',
    is_flag=True,
    help='Show version'
)
def main(
    input_path: Optional[str],
    output_path: Optional[str],
    output_format: str,
    config_path: Optional[str],
    api_key: Optional[str],
    version: bool
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
    if version:
        click.echo(f"audio-to-subs v{__version__}")
        return
    
    # Validate configuration
    if config_path and (input_path or output_path):
        click.echo(
            "Error: --config cannot be used with --input or --output",
            err=True
        )
        sys.exit(1)
    
    # Batch processing mode
    if config_path:
        _process_batch(config_path, api_key)
        return
    
    # Single video processing
    if not input_path:
        click.echo("Error: --input is required", err=True)
        sys.exit(1)
    
    if not output_path:
        click.echo("Error: --output is required", err=True)
        sys.exit(1)
    
    if not api_key:
        click.echo(
            "Error: API key required. Provide with --api-key or set MISTRAL_API_KEY",
            err=True
        )
        sys.exit(1)
    
    # Check input file exists
    if not Path(input_path).exists():
        click.echo(f"Error: Input file not found: {input_path}", err=True)
        sys.exit(1)
    
    try:
        # Create progress callback
        def progress_callback(message: str) -> None:
            """Display progress message to user.
            
            Args:
                message: Progress status message
            """
            click.echo(f"[*] {message}")
        
        # Initialize pipeline
        pipeline = Pipeline(
            api_key=api_key,
            progress_callback=progress_callback
        )
        
        # Process video
        click.echo(f"Processing: {input_path}")
        result = pipeline.process_video(
            input_path,
            output_path,
            output_format=output_format
        )
        
        click.echo(f"\n✓ Success! Subtitles saved to: {result}")
        
    except PipelineError as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: Unexpected error - {str(e)}", err=True)
        sys.exit(1)


def _process_batch(config_path: str, api_key: Optional[str]) -> None:
    """Process multiple videos from configuration file.
    
    Args:
        config_path: Path to .audio-to-subs.yaml configuration file
        api_key: Mistral AI API key
        
    Raises:
        SystemExit: On error
    """
    if not api_key:
        click.echo(
            "Error: API key required. Provide with --api-key or set MISTRAL_API_KEY",
            err=True
        )
        sys.exit(1)
    
    try:
        # Parse configuration
        config = ConfigParser(config_path)
        config.validate()
        jobs = config.get_jobs()
        
        # Create progress callback
        def progress_callback(message: str) -> None:
            click.echo(f"[*] {message}")
        
        # Initialize pipeline
        pipeline = Pipeline(
            api_key=api_key,
            progress_callback=progress_callback
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
        sys.exit(1)
    except PipelineError as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: Unexpected error - {str(e)}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
