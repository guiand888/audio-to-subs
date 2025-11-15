"""Command-line interface for audio-to-subs."""
import os
import sys
import click
from pathlib import Path

from src.pipeline import Pipeline, PipelineError

__version__ = "0.1.0"


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
    help='Output SRT subtitle file path'
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
def main(input_path, output_path, api_key, version):
    """Convert video audio to SRT subtitles using Mistral AI transcription.
    
    \b
    Usage:
      audio-to-subs -i video.mp4 -o output.srt --api-key YOUR_KEY
      
    Or set MISTRAL_API_KEY environment variable:
      export MISTRAL_API_KEY=your_key
      audio-to-subs -i video.mp4 -o output.srt
    """
    if version:
        click.echo(f"audio-to-subs v{__version__}")
        return
    
    # Validate inputs
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
        def progress_callback(message: str):
            click.echo(f"[*] {message}")
        
        # Initialize pipeline
        pipeline = Pipeline(
            api_key=api_key,
            progress_callback=progress_callback
        )
        
        # Process video
        click.echo(f"Processing: {input_path}")
        result = pipeline.process_video(input_path, output_path)
        
        click.echo(f"\n✓ Success! Subtitles saved to: {result}")
        
    except PipelineError as e:
        click.echo(f"Error: {str(e)}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: Unexpected error - {str(e)}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
