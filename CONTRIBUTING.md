# Contributing

Local development uses **Nix** (`nix develop`) for a reproducible toolchain — nothing is hand-installed on the host.

## Prerequisites

- **Nix** (with flakes enabled): local development toolchain
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

## Container Architecture

### Local Development (`nix develop`)

- **Defined in**: `flake.nix`
- **`default` shell**: Python 3.11 + build toolchain, `ffmpeg`, `redis`, Node 24 — full backend + frontend dev tools (pytest, black, ruff, mypy, npm)
- **`frontend` shell** (`nix develop .#frontend`): lean, Node-only shell for frontend-only work
- **State**: bootstraps `.venv` in the repo root on first entry, gated on a hash of `requirements.txt`/`requirements-dev.txt`/`pyproject.toml` so it only reinstalls when they change

**Usage**: Development, testing, code quality checks (also what CI runs, via `nix develop`)

## Typical Workflow

### Initial Setup

1. **Enter dev shell**: `nix develop` (or `make shell`)
2. **Verify installation**: check tools (see Quick Start above)
3. **Create API secret**: `make secret-create`

### Development Cycle (TDD)

1. **Write failing test**: Edit `tests/test_*.py`
2. **Run tests**: `make test` (should fail)
3. **Implement code**: Edit `audio_to_subs/*.py`
4. **Run tests**: `make test` (should pass)
5. **Check quality**: `make quality`
6. **Commit changes**

## Troubleshooting

### Dev Shell Won't Build / Deps Out of Date

```bash
# Force a clean rebuild of the venv
rm -rf .venv
nix develop

# Check nix itself is healthy
nix flake check
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

For detailed deployment documentation, see the developer docs in `docs/dev/`.