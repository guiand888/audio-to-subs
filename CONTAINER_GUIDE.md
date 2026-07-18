# Development & Container Guide

## Overview

Local development uses **Nix** (`nix develop`) for a reproducible toolchain — nothing is hand-installed on the host. Production deployment is **container-first** with Podman.

## Prerequisites

- **Nix** (with flakes enabled): local development toolchain
- **Podman**: Container runtime (Docker-compatible), for production builds/deployment
- **Podman Compose**: Multi-container orchestration
- **Mistral AI API Key**: For transcription service

## Quick Start

### 1. Enter the Dev Shell

```bash
nix develop
# bootstraps .venv and installs Python + frontend deps automatically
```

### 2. Verify the Shell

```bash
python --version   # Should be 3.11.x
ffmpeg -version    # Should be installed
pytest --version   # Should be installed
node --version     # Should be 24.x
```

### 3. Run Tests

```bash
make test
# or, from inside `nix develop`:
pytest
```

## Common Commands

### Development

```bash
# Open the nix dev shell (backend + frontend toolchain)
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

### Local Development (`nix develop`)

- **Defined in**: `flake.nix`
- **`default` shell**: Python 3.11 + build toolchain, `ffmpeg`, `redis`, Node 24 — full backend + frontend dev tools (pytest, black, ruff, mypy, npm)
- **`frontend` shell** (`nix develop .#frontend`): lean, Node-only shell for frontend-only work
- **State**: bootstraps `.venv` in the repo root on first entry, gated on a hash of `requirements.txt`/`requirements-dev.txt`/`pyproject.toml` so it only reinstalls when they change

**Usage**: Development, testing, code quality checks (also what CI runs, via `nix develop`)

### Production Container (`Dockerfile`)

- **Base**: `python:3.11-alpine` (multi-stage build)
- **Includes**: Only runtime dependencies
- **User**: `appuser` (UID 1000, non-root)
- **Working Dir**: `/app`
- **Volumes**: `/input` (videos), `/output` (subtitles), `/tmp/parolesub` (temp)
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

By default, `docker-compose.yml` / `docker-compose.docker.yml` build
`backend`/`worker`/`frontend` from the GitHub repo at a pinned tag
(`build.context` is a Git URL), not the local checkout — so `podman compose
up -d --build` works straight after cloning, with no separate build step.
For local development, where you want the working tree's uncommitted
changes actually built, layer `docker-compose.dev.yml` on top to restore a
local `build.context`:

```bash
podman compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

See `DEPLOY_QUICKSTART.md` for the full deployment options.

### File Structure

```yaml
services:
  parolesub:
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
podman-compose run parolesub -i /input/video.mp4 -o /output

# View logs
podman-compose logs -f

# Stop service
podman-compose down
```

## Typical Workflow

### Initial Setup

1. **Enter dev shell**: `nix develop` (or `make shell`)
2. **Verify installation**: check tools (see Quick Start above)
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

### Dev Shell Won't Build / Deps Out of Date

```bash
# Force a clean rebuild of the venv
rm -rf .venv
nix develop

# Check nix itself is healthy
nix flake check
```

### Production Container Won't Build

```bash
# Check Podman is running
podman info

# Clean up old images
make clean

# Rebuild from scratch
podman build --no-cache -t parolesub:latest .
```

### Tests Fail

```bash
# Enter the dev shell
nix develop

# Run tests with verbose output
pytest -vv
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
    target: /tmp/parolesub
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
nix develop --command pytest -n auto
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
  name: parolesub
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: parolesub
        image: parolesub:latest
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

**Remember**: Local development happens inside the Nix dev shell (`nix develop`) — never install Python/Node packages directly on the host. Production always runs in containers.
