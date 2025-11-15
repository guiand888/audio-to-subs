# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

**audio-to-subs** - Python CLI tool for converting video audio to subtitles using AI transcription.

- **Language**: Python 3.9+
- **Architecture**: Pipeline-based (Extract → Transcribe → Generate)
- **AI Model**: Mistral AI Voxtral Mini Transcribe
- **License**: GPLv3

## Development Setup

### Prerequisites
- **Podman** (container runtime - no Docker)
- **Podman Compose** (for multi-container scenarios)
- **Mistral AI API key**
- **No local Python installation required** (development in containers)

### Container-First Development

**IMPORTANT**: This project uses container-first development. Nothing is installed locally on the developer workstation.

#### Quick Start
```bash
# Build development container
podman build -t audio-to-subs:dev -f Dockerfile.dev .

# Run tests in container (preserves your UID/GID)
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev pytest

# Interactive development shell
podman run --rm -it --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev /bin/sh

# Build production image
podman build -t audio-to-subs:latest .
```

#### Configure API Key (Podman Secrets)
```bash
# Create secret for API key
echo "your_api_key_here" | podman secret create mistral_api_key -

# Or from file
podman secret create mistral_api_key ~/.config/mistral/api_key

# List secrets
podman secret ls
```

### Running Tests (Containerized)
```bash
# All tests with coverage (preserves your UID/GID)
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev pytest

# Specific test file
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev pytest tests/test_audio_extractor.py

# BDD scenarios
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev pytest features/

# With verbose output
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev pytest -v
```

### Code Quality (Containerized)
```bash
# Format code (preserves your UID/GID)
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev black src/ tests/

# Lint
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev ruff check src/ tests/

# Type check
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev mypy src/

# Run all quality checks
podman run --rm --userns=keep-id -v .:/app:Z,rslave audio-to-subs:dev make quality
```

### Production Usage
```bash
# Run with Podman (preserves your UID/GID for output files)
podman run --rm \
  --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v ./videos:/input:ro,Z \
  -v ./subtitles:/output:Z \
  audio-to-subs:latest -i /input/video.mp4 -o /output

# Or with Podman Compose
podman-compose up
```

**Important Flags**:
- `--userns=keep-id`: Preserves your host UID/GID in the container, ensuring output files are owned by your user
- `,Z` flag (comma-separated): Applies SELinux relabeling to the volume mount, preventing permission issues on Fedora/RHEL systems
- `--secret mistral_api_key,type=env,target=MISTRAL_API_KEY`: Mounts Podman secret as environment variable (ensures API key doesn't have trailing newline)

## Architecture

See `ARCHITECTURE.md` for detailed architecture documentation.

**Key Components**:
- `audio_extractor.py`: FFmpeg wrapper for audio extraction
- `transcription_client.py`: Mistral AI API client
- `subtitle_generator.py`: SRT file generation
- `pipeline.py`: Workflow orchestration
- `cli.py`: Command-line interface

**Pipeline Flow**:
```
Video → Audio Extraction → AI Transcription → SRT Generation → Output
```

## Testing

Following TDD/BDD methodology:
- **BDD**: Gherkin scenarios in `features/`
- **TDD**: Unit tests in `tests/`
- **Target**: >80% code coverage

## Development Status

**Current Phase**: Phase 1 - Project Foundation ✅
- [x] Project structure created
- [x] BDD scenarios defined
- [x] Configuration files setup
- [ ] Virtual environment and dependencies
- [ ] First component (audio_extractor) TDD cycle

See `ROADMAP.md` for detailed implementation plan.

## License

All code must comply with GPLv3 requirements.
