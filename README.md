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
- Container-first development (Podman)
- Full test coverage with TDD/BDD

## Quick Start

### Using Containers (Recommended)

```bash
# Build development container
make build-dev

# Run tests
make test

# Interactive shell
make shell
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
# Convert single video
podman run --rm \
  --secret mistral_api_key \
  -v ./videos:/input:ro \
  -v ./subtitles:/output \
  audio-to-subs:latest -i /input/video.mp4 -o /output/video.srt

# Specify output format (default: srt)
podman run --rm \
  --secret mistral_api_key \
  -v ./videos:/input:ro \
  -v ./subtitles:/output \
  audio-to-subs:latest -i /input/video.mp4 -o /output/video.vtt --format vtt
```

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
  --secret mistral_api_key \
  -v $(pwd):/work \
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

## Development

This project follows TDD/BDD methodology with container-first development.

See `WARP.md` for detailed development guidance and `ARCHITECTURE.md` for system design.

### Running Tests

```bash
# All tests
make test

# Specific test file
make test-file TEST=tests/test_pipeline.py

# With coverage
make coverage
```

### Code Quality

```bash
# Format code
make format

# Lint and type check
make lint
make typecheck

# All quality checks
make quality
```

## API Reference

For programmatic usage:

```python
from src.pipeline import Pipeline

pipeline = Pipeline(api_key="your_key")
output = pipeline.process_video(
    video_path="video.mp4",
    output_path="subtitles.srt",
    output_format="srt"  # srt, vtt, webvtt, sbv
)
```

## Requirements

- Podman (container runtime)
- Mistral AI API key (get from https://console.mistral.ai)
- FFmpeg (included in container)
- Python 3.9+ (in container)

## License

GPLv3 - See LICENSE file for details.

## Author

Guillaume Andre (@guiand888)
