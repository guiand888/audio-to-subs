# audio-to-subs

Convert video audio to subtitles using AI-powered transcription.

## Overview

**audio-to-subs** is a Python CLI tool that extracts audio from video files, transcribes it using Mistral AI's Voxtral Mini model, and generates accurate subtitle files in multiple formats (SRT, VTT, WebVTT, SBV).

## Features

- Extract audio from video files (.mp4, .mkv, .avi, etc.)
- AI-powered transcription using Mistral AI Voxtral Mini
- Generate timestamped subtitles in multiple formats:
  - SRT (SubRip)
  - VTT (WebVTT)
  - SBV (YouTube)
- Single video and batch processing
- Configuration file support (.audio-to-subs.yaml)
- **Enhanced Progress Reporting**
  - Visual progress bars with percentage indicators
  - Real-time upload progress tracking (1MB chunks)
  - Multi-stage progress monitoring (audio extraction, upload, transcription, generation)
  - Segment-level progress for large files
  - Configurable verbosity levels
- **Subtitle Naming Conventions**
  - Automatic language code inclusion in filenames
  - Bazarr and media player compatibility
  - ISO 639-1/2 language code support (en, fr, es, de, etc.)
  - Proper filename format: `filename.language_code.format`
- Container-first development (Podman)
- Full test coverage with TDD/BDD

## Quick Start

### Build Container

```bash
# Build production image
podman build -t audio-to-subs:latest .
```

### Configuration

Set your Mistral AI API key:

```bash
# Using Podman secrets (recommended)
echo "your_api_key" | podman secret create mistral_api_key -

# Or using environment variable
export MISTRAL_API_KEY=your_api_key
```

### Usage

#### Single Video

```bash
# Convert single video (preserves your UID/GID for output files)
podman run --rm \
  --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v ./videos:/input:ro,Z \
  -v ./subtitles:/output:Z \
  audio-to-subs:latest -i /input/video.mp4 -o /output/video.srt

# With progress reporting (visual progress bars)
podman run --rm \
  --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v ./videos:/input:ro,Z \
  -v ./subtitles:/output:Z \
  audio-to-subs:latest -i /input/video.mp4 -o /output/video.srt --progress

# Specify output format (default: srt)
podman run --rm \
  --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v ./videos:/input:ro,Z \
  -v ./subtitles:/output:Z \
  audio-to-subs:latest -i /input/video.mp4 -o /output/video.vtt --format vtt
```

**Important**: Use `--userns=keep-id` to preserve your user ID/GID on output files, preventing permission issues.

#### Batch Processing

Create `.audio-to-subs.yaml` in your working directory:

```yaml
jobs:
  - input: ./videos/video1.mp4
    output: ./subtitles/video1.srt
  - input: ./videos/video2.mp4
    output: ./subtitles/video2.vtt
    format: vtt
```

Then run:

```bash
podman run --rm \
  --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v $(pwd):/work:Z,rslave \
  audio-to-subs:latest --config /work/.audio-to-subs.yaml
```

Or with docker-compose:

```bash
podman-compose up
```

## Configuration File (.audio-to-subs.yaml)

The configuration file supports batch processing with custom settings:

```yaml
# Default settings for all jobs
defaults:
  format: srt  # srt, vtt, webvtt, sbv
  temp_dir: /tmp/audio-to-subs

jobs:
  - input: videos/meeting.mp4
    output: subtitles/meeting.srt
  - input: videos/presentation.mkv
    output: subtitles/presentation.vtt
    format: vtt  # Override default format
  - input: videos/tutorial.avi
    output: subtitles/tutorial.sbv
    format: sbv
```

## Subtitle Naming Conventions

The system automatically generates subtitle filenames following industry standards for Bazarr and media player compatibility.

### Language Code Support

When you specify a language code using the `--language` parameter, the generated subtitle filename will include the language code:

```bash
audio-to-subs -i video.mp4 -o output.srt --language en
# Generates: output.en.srt

audio-to-subs -i movie.mp4 -o subtitles.srt --language fr
# Generates: subtitles.fr.srt
```

### Supported Language Codes

The system supports ISO 639-1 (2-letter) and ISO 639-2 (3-letter) language codes:

- **2-letter codes**: en, fr, es, de, it, pt, ru, zh, ja, ko
- **3-letter codes**: eng, fra, spa, deu, ita, por, rus, zho, jpn, kor

### Filename Format

```
base_filename.language_code.format
```

Examples:
- `movie.en.srt` (English SRT subtitles)
- `show.s01e01.fr.vtt` (French WebVTT subtitles)
- `documentary.de.sbv` (German YouTube subtitles)

### Media Player Compatibility

These naming conventions are supported by:
- **Plex**: Automatic subtitle detection and selection
- **Jellyfin**: Full subtitle naming support
- **Kodi**: Recognizes standard naming patterns
- **VLC**: Automatic subtitle loading
- **MPV**: Recognizes subtitle files with matching base names
- **Bazarr**: Expected subtitle file naming for automated management

### Usage Examples

```bash
# Generate English subtitles
audio-to-subs -i video.mp4 -o output.srt --language en

# Generate French subtitles
audio-to-subs -i video.mp4 -o output.srt --language fr

# Generate Spanish subtitles in VTT format
audio-to-subs -i video.mp4 -o output.vtt --language es --format vtt

# Batch processing with language codes
# .audio-to-subs.yaml
jobs:
  - input: videos/movie.mp4
    output: subtitles/movie.srt
    # Note: Language is set via CLI --language parameter
```

## Output Formats

### SRT (SubRip) - Default

Wide compatibility with video players and editing software.

```
1
00:00:01,000 --> 00:00:05,000
First subtitle line

2
00:00:05,500 --> 00:00:10,000
Second subtitle line
```

### VTT (WebVTT)

Web standard subtitle format.

```
WEBVTT

00:00:01.000 --> 00:00:05.000
First subtitle line

00:00:05.500 --> 00:00:10.000
Second subtitle line
```

### WebVTT (Full)

WebVTT with optional metadata and styling.

### SBV (YouTube)

YouTube's legacy subtitle format.

```
0:00:01,000
0:00:05,000
First subtitle line

0:00:05,500
0:00:10,000
Second subtitle line
```

## Installation

### Local Development (with venv)

```bash
# Clone repository
git clone https://github.com/guiand888/audio-to-subs.git
cd audio-to-subs

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Verify installation
audio-to-subs --help
```

### Docker/Podman

```bash
# Build development container
podman build -f Dockerfile.dev -t audio-to-subs:dev .

# Build production container
podman build -t audio-to-subs:latest .

# Run with Podman
podman run --rm -it audio-to-subs:latest --help
```

## Testing

### Run All Tests

```bash
# With coverage report
pytest tests/ -v --cov=src --cov-report=html

# Quick test run
pytest tests/ -v --no-cov

# Run specific test file
pytest tests/test_pipeline.py -v
```

### Run BDD Scenarios

```bash
# Run feature tests
pytest features/steps/ -v

# Run specific feature
pytest features/steps/audio_steps.py -v
```

### Test Coverage

Current test coverage: **120 tests passing, 3 skipped**

- Audio extraction: 7 tests
- Subtitle generation: 14 tests
- Pipeline orchestration: 7 tests
- CLI interface: 9 tests
- Configuration parsing: 18 tests
- Format conversions: 25 tests
- Audio splitting: 25 tests
- Logging: 12 tests
- Integration tests: 3 tests (skipped - require API key)

Target coverage: >80% ✅

## Troubleshooting

### FFmpeg Not Found

**Error**: `FFmpeg not found or not in PATH`

**Solution**:
```bash
# Install FFmpeg
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Verify installation
ffmpeg -version
```

### API Key Issues

**Error**: `Error: API key required. Provide with --api-key or set MISTRAL_API_KEY`

**Solution**:
```bash
# Set environment variable
export MISTRAL_API_KEY=your_api_key

# Or pass directly
audio-to-subs -i video.mp4 -o output.srt --api-key your_api_key

# Get API key from https://console.mistral.ai
```

### Permission Denied on Output Files

**Error**: `Permission denied: 'output.srt'`

**Solution** (with Podman):
```bash
# Use --userns=keep-id to preserve user permissions
podman run --rm --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v ./videos:/input:ro,Z \
  -v ./subtitles:/output:Z \
  audio-to-subs:latest -i /input/video.mp4 -o /output/video.srt
```

### Large Video Files

**Issue**: Processing takes a long time or runs out of memory

**Solution**:
- Audio files >15 minutes are automatically split into segments
- Each segment is transcribed separately
- Timestamps are automatically adjusted
- Temporary files are cleaned up automatically

### Unsupported Video Format

**Error**: `Audio extraction failed: Unsupported video format`

**Solution**:
```bash
# Convert video to supported format first
ffmpeg -i input.mov -c:v libx264 -c:a aac output.mp4

# Supported formats: mp4, mkv, avi, mov, flv, wmv, webm
```

## Development

### Project Structure

```
audio-to-subs/
├── src/                          # Source code
│   ├── __main__.py              # Entry point
│   ├── cli.py                   # CLI interface
│   ├── pipeline.py              # Main orchestrator
│   ├── audio_extractor.py       # FFmpeg wrapper
│   ├── audio_splitter.py        # Large file handling
│   ├── transcription_client.py  # Mistral AI client
│   ├── subtitle_generator.py    # Format generators
│   ├── config_parser.py         # YAML config parsing
│   └── logging_config.py        # Logging setup
├── tests/                        # Unit tests (120 tests)
├── features/                     # BDD scenarios
│   └── steps/                   # Step implementations
├── Dockerfile                    # Production container
├── Dockerfile.dev               # Development container
├── docker-compose.yml           # Compose configuration
├── pyproject.toml               # Project metadata
└── README.md                    # This file
```

### Development Workflow

1. **Write tests first** (TDD)
   ```bash
   pytest tests/test_new_feature.py -v
   ```

2. **Implement feature**
   ```bash
   # Edit src/new_feature.py
   ```

3. **Run tests**
   ```bash
   pytest tests/ -v --cov=src
   ```

4. **Code quality checks**
   ```bash
   black src/
   ruff check src/
   mypy src/
   ```

### Running in Development Container

```bash
# Build dev container
podman build -f Dockerfile.dev -t audio-to-subs:dev .

# Run tests in container
podman run --rm -v .:/app:Z audio-to-subs:dev pytest tests/ -v

# Interactive shell
podman run --rm -it -v .:/app:Z audio-to-subs:dev bash

# Run CLI in container
podman run --rm -v ./videos:/input:ro,Z -v ./output:/output:Z \
  -e MISTRAL_API_KEY=your_key \
  audio-to-subs:dev -i /input/video.mp4 -o /output/video.srt
```

## API Reference

For programmatic usage:

```python
from src.pipeline import Pipeline

# Initialize pipeline
pipeline = Pipeline(api_key="your_key")

# Process single video
output = pipeline.process_video(
    video_path="video.mp4",
    output_path="subtitles.srt",
    output_format="srt"  # srt, vtt, webvtt, sbv
)

# Process batch
jobs = [
    {"input": "video1.mp4", "output": "sub1.srt"},
    {"input": "video2.mp4", "output": "sub2.vtt", "format": "vtt"}
]
results = pipeline.process_batch(jobs)

# With progress callback (enhanced with percentages)
def on_progress(message, percentage=None):
    if percentage:
        print(f"[Progress {percentage}%] {message}")
    else:
        print(f"[Progress] {message}")

pipeline = Pipeline(
    api_key="your_key",
    progress_callback=on_progress,
    verbose_progress=True  # Show upload and segment progress with percentages
)
```

## Progress Reporting

The enhanced progress reporting system provides detailed feedback during processing:

### Progress Stages

1. **Audio Extraction (0-25%)**: Extracting audio from video file
2. **Audio Upload (25-50%)**: Uploading audio to Mistral AI (with chunked progress)
3. **Transcription Processing (50-75%)**: Processing transcription results
4. **Subtitle Generation (75-100%)**: Generating final subtitle files

### CLI Progress Flags

- `--progress`: Show visual progress bars with percentage indicators
- `--verbose`: Show detailed progress messages
- Combine both for comprehensive progress reporting

### Progress Callback Signature

```python
def progress_callback(message: str, percentage: int = None):
    """
    Progress callback function signature
    
    Args:
        message: Progress message text
        percentage: Optional percentage (0-100) for progress bars
    """
    pass
```

### Example Progress Output

```
[Progress 10%] Extracting audio from video...
[Progress 25%] Audio extraction complete
[Progress 30%] Audio ready for transcription
[Progress 30%] Transcribing audio with Mistral AI...
[Progress 30%] Uploading segment 1/1: 0.0/1.5 MB (0%)
[Progress 35%] Uploading segment 1/1: 0.5/1.5 MB (33%)
[Progress 45%] Uploading segment 1/1: 1.5/1.5 MB (100%)
[Progress 75%] Transcription processing complete
[Progress 75%] Generating SRT subtitles...
[Progress 100%] Subtitle generation complete
[Progress 100%] Complete! Subtitles generated successfully.
```

### Upload Progress Tracking

- Files are uploaded in 1MB chunks for smooth progress updates
- Real-time percentage tracking during upload
- Segment-level progress for large files split into multiple parts
- Visual progress bars show upload completion

### Programmatic Usage

```python
# Enhanced progress callback with upload tracking
def detailed_progress(message, percentage=None):
    if "Uploading" in message and percentage:
        print(f"📤 {message}")
    elif percentage:
        print(f"[{percentage:3d}%] {message}")
    else:
        print(f"→ {message}")

pipeline = Pipeline(
    api_key="your_key",
    progress_callback=detailed_progress,
    verbose_progress=True
)

# Process with detailed progress
pipeline.process_video("video.mp4", "subtitles.srt")
```

## Requirements

- **Runtime**: Podman or Docker
- **API**: Mistral AI API key (get from https://console.mistral.ai)
- **Python**: 3.9+ (for local development)
- **FFmpeg**: 4.0+ (included in containers)

## Performance

- **Single video**: ~1-2 minutes (depends on video length and API response time)
- **Batch processing**: Processes videos sequentially
- **Memory usage**: ~200MB base + audio buffer
- **Disk usage**: Temporary audio files cleaned up automatically

## Contributing

This project follows strict development standards:

- **Code Style**: Black formatter, Ruff linter
- **Type Checking**: MyPy with strict mode
- **Testing**: TDD/BDD with >80% coverage
- **Git Workflow**: Feature branches, pull requests, code review

See `dev/QUALITY.md` for detailed standards.

## Development Standards & Instructions

Comprehensive development rules, coding standards, and project guidelines are maintained in a separate repository and referenced during development. These include standards for:

- Code quality and style
- Testing methodologies (TDD/BDD)
- Git workflow and collaboration
- Architecture and design patterns
- Deployment practices

For access to these standards, contact the project maintainers or see the development team setup documentation.

## License

GPLv3 - See LICENSE file for details.

## Author

Guillaume Andre (@guiand888)
