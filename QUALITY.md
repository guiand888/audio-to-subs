# Quality Checks

This document describes code quality standards and tools for the audio-to-subs project.

## Quick Start

### Run All Quality Checks

```bash
make quality
```

This runs:
1. Code formatting check (black)
2. Linting (ruff)
3. Type checking (mypy)
4. Tests (pytest)

### Individual Checks

```bash
# Format code
make format

# Check formatting only (doesn't modify)
make format-check

# Lint code
make lint

# Type check
make typecheck

# Run tests
make test

# Run tests with coverage
make test-cov
```

## Tools

### Black

Code formatter ensuring consistent style.

```bash
# In container
podman run --rm -v ./:/app:Z audio-to-subs:dev black src/ tests/

# Or
make format
```

**Configuration**: `pyproject.toml`
- Line length: 88
- Target Python: 3.9+

### Ruff

Fast Python linter and code analyzer.

```bash
# Check
podman run --rm -v ./:/app:Z audio-to-subs:dev ruff check src/ tests/

# Fix
podman run --rm -v ./:/app:Z audio-to-subs:dev ruff check --fix src/ tests/
```

**Configuration**: `pyproject.toml`
- Rules: E, W, F, I, C, B, UP
- Ignores: E501 (line length, handled by black)

### MyPy

Static type checker for Python.

```bash
podman run --rm -v ./:/app:Z audio-to-subs:dev mypy src/
```

**Configuration**: `pyproject.toml`
- Mode: Strict
- Python version: 3.9
- Checks all function signatures

### Pytest

Unit and integration testing framework.

```bash
# Run all tests
podman run --rm -v ./:/app:Z audio-to-subs:dev pytest

# Run with coverage
podman run --rm -v ./:/app:Z audio-to-subs:dev pytest --cov

# Watch mode
podman run --rm -it -v ./:/app:Z audio-to-subs:dev pytest -f
```

**Configuration**: `pyproject.toml`
- Test paths: `tests/`, `features/`
- Markers: `unit`, `integration`, `e2e`
- Coverage reports: HTML in `htmlcov/`

## Pre-commit Hooks

Automated quality checks run before each commit.

### Setup

```bash
# In container
podman run --rm -it -v ./:/app:Z audio-to-subs:dev pre-commit install

# Or outside container (requires local git)
pre-commit install
```

### Usage

```bash
# Run hooks on staged files
pre-commit run --all-files

# Bypass hooks (not recommended)
git commit --no-verify
```

**Hooks**: `.pre-commit-config.yaml`
- Trailing whitespace
- End-of-file fixer
- YAML validation
- Black formatting
- Ruff linting and fixing
- MyPy type checking

## Standards

### Python Style

- Follow PEP 8
- Use type hints for all functions
- Docstrings for public APIs
- Line length: 88 characters

### Naming

- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_CASE`
- Private members: `_leading_underscore`

### Testing

- Minimum coverage: 80%
- Unit tests: `tests/test_*.py`
- BDD scenarios: `features/*.feature`
- Test all public APIs

### Commits

- Concise, descriptive messages
- Prefix with type: `feat:`, `fix:`, `docs:`, `test:`, etc.
- Examples:
  - `feat: add batch processing`
  - `fix: resolve VTT timestamp formatting`
  - `docs: update README with examples`

## Continuous Integration

Quality checks run in CI/CD pipeline for all pull requests.

Required to pass:
- All tests pass
- Code coverage maintained
- No linting errors
- Type checking passes
- Code formatting valid

## Troubleshooting

### MyPy strict mode

If encountering type errors, ensure:

```python
def function(arg: str) -> str:
    """Function with proper type hints."""
    return arg.upper()
```

### Import sorting

Let ruff fix imports automatically:

```bash
podman run --rm -v ./:/app:Z audio-to-subs:dev ruff check --fix src/
```

### Formatting conflicts

If black and ruff disagree, black takes precedence:

```bash
make format-check lint
```

## Further Reading

- [Black Documentation](https://black.readthedocs.io/)
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [MyPy Documentation](https://mypy.readthedocs.io/)
- [Pytest Documentation](https://docs.pytest.org/)
- [Pre-commit Framework](https://pre-commit.com/)
