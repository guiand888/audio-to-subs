# audio-to-subs

Convert video audio to subtitles using AI-powered transcription.

## Overview

**audio-to-subs** is a Python CLI tool that extracts audio from video files, transcribes it using Mistral AI's Voxtral Mini model, and generates accurate SRT subtitle files.

## Features

- Extract audio from video files (.mp4, .mkv, .avi, etc.)
- AI-powered transcription using Mistral AI
- Generate timestamped SRT subtitle files
- Batch processing support
- Container-first development (Podman)

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

```bash
# Convert single video
podman run --rm \
  --secret mistral_api_key \
  -v ./videos:/input:ro \
  -v ./subtitles:/output \
  audio-to-subs:latest -i /input/video.mp4 -o /output

# Using docker-compose
podman-compose up
```

## Development

This project follows TDD/BDD methodology with container-first development.

See `WARP.md` for detailed development guidance.

## Requirements

- Podman (container runtime)
- Mistral AI API key

## License

GPLv3 - See LICENSE file for details.

## Author

Guillaume Andre (@guiand888)
