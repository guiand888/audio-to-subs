# Container Development Guide

## Overview

This project uses **container-first development** with Podman. Nothing is installed on the host workstation—all development happens inside containers.

## Prerequisites

- **Podman**: Container runtime (Docker-compatible)
- **Podman Compose**: Multi-container orchestration
- **Mistral AI API Key**: For transcription service

## Quick Start

### 1. Build Development Container

```bash
make build-dev
# or
podman build -t audio-to-subs:dev -f Dockerfile.dev .
```

### 2. Verify Container

```bash
# Open shell in container
make shell

# Inside container, verify tools:
python --version   # Should be 3.11
ffmpeg -version    # Should be installed
pytest --version   # Should be installed
```

### 3. Run Tests

```bash
make test
# or
podman run --rm -v .:/app:Z audio-to-subs:dev pytest
```

## Common Commands

### Development

```bash
# Build development container
make build-dev

# Open interactive shell
make shell

# Run tests
make test

# Run tests with coverage
make test-cov

# Format code
make format

# Lint code
make lint

# Type check
make typecheck

# Run all quality checks
make quality
```

### Production

```bash
# Build production container
make build

# Run production container (requires setup)
make run

# Using Podman Compose
make compose-up
make compose-logs
make compose-down
```

### Secrets Management

```bash
# Create API key secret (interactive)
make secret-create

# Create from file
podman secret create mistral_api_key ~/.config/mistral/api_key

# List secrets
make secret-list

# Remove secret
make secret-rm
```

## Container Architecture

### Development Container (`Dockerfile.dev`)

- **Base**: `python:3.11-alpine`
- **Includes**: All dev tools (pytest, black, ruff, mypy)
- **User**: `developer` (UID 1000)
- **Working Dir**: `/app`
- **Volume Mount**: Host directory mounted at `/app`

**Usage**: Development, testing, code quality checks

### Production Container (`Dockerfile`)

- **Base**: `python:3.11-alpine` (multi-stage build)
- **Includes**: Only runtime dependencies
- **User**: `appuser` (UID 1000, non-root)
- **Working Dir**: `/app`
- **Volumes**: `/input` (videos), `/output` (subtitles), `/tmp/audio-to-subs` (temp)
- **Entry Point**: `python -m video_to_subtitles_pipeline`

**Usage**: Production deployment, actual video processing

## Volume Mounts

### Development (SELinux `:Z` flag)

```bash
-v .:/app:Z    # Mounts current directory with SELinux relabeling
```

### Production

```bash
-v ./videos:/input:ro          # Input videos (read-only)
-v ./subtitles:/output:rw      # Output subtitles (read-write)
```

## Podman Compose

### File Structure

```yaml
services:
  audio-to-subs:
    build: .
    secrets:
      - mistral_api_key
    volumes:
      - ./videos:/input:ro
      - ./subtitles:/output
    user: "1000:1000"
```

### Usage

```bash
# Start service
podman-compose up

# Run single video
podman-compose run audio-to-subs -i /input/video.mp4 -o /output

# View logs
podman-compose logs -f

# Stop service
podman-compose down
```

## Typical Workflow

### Initial Setup

1. **Build dev container**: `make build-dev`
2. **Verify installation**: `make shell` then check tools
3. **Create API secret**: `make secret-create`

### Development Cycle (TDD)

1. **Write failing test**: Edit `tests/test_*.py`
2. **Run tests**: `make test` (should fail)
3. **Implement code**: Edit `src/video_to_subtitles_pipeline/*.py`
4. **Run tests**: `make test` (should pass)
5. **Check quality**: `make quality`
6. **Commit changes**

### Production Deployment

1. **Build production image**: `make build`
2. **Test with sample video**: `make run`
3. **Deploy with compose**: `make compose-up`

## Troubleshooting

### Container Won't Build

```bash
# Check Podman is running
podman info

# Clean up old images
make clean

# Rebuild from scratch
podman build --no-cache -t audio-to-subs:dev -f Dockerfile.dev .
```

### Tests Fail in Container

```bash
# Get interactive shell
make shell

# Inside container, run tests with verbose output
pytest -vv

# Check file permissions
ls -la /app
```

### Volume Mount Issues (SELinux)

```bash
# On Fedora/RHEL, use :Z flag for SELinux relabeling
podman run -v .:/app:Z ...

# Or temporarily set SELinux to permissive (not recommended)
sudo setenforce 0
```

### Secret Not Found

```bash
# Verify secret exists
podman secret ls

# Recreate secret
podman secret rm mistral_api_key
make secret-create
```

## Performance Tips

### Use tmpfs for Temp Files

```yaml
volumes:
  - type: tmpfs
    target: /tmp/audio-to-subs
    tmpfs:
      size: 1G
```

### Resource Limits

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 2G
```

### Parallel Testing

```bash
# Run tests in parallel (future enhancement)
podman run --rm -v .:/app:Z audio-to-subs:dev pytest -n auto
```

## Security Best Practices

1. **Non-root user**: Containers run as UID 1000
2. **Read-only volumes**: Input videos mounted `:ro`
3. **Secrets**: Use Podman secrets, never environment variables
4. **Minimal base**: Alpine Linux for reduced attack surface
5. **No new privileges**: `--security-opt no-new-privileges:true`

## Kubernetes Deployment (Future)

### Basic Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: audio-to-subs
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: audio-to-subs
        image: audio-to-subs:latest
        env:
        - name: MISTRAL_API_KEY
          valueFrom:
            secretKeyRef:
              name: mistral-api-key
              key: key
        volumeMounts:
        - name: videos
          mountPath: /input
        - name: subtitles
          mountPath: /output
```

## Help

```bash
# List all available make targets
make help

# Podman help
podman --help
podman run --help
podman-compose --help
```

---

**Remember**: All development happens in containers. Never install Python packages on the host!
