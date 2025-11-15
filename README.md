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

For development setup and testing, see `dev/WARP.md` in the development repository.

This project follows TDD/BDD methodology with container-first development.

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
