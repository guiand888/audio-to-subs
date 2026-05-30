# Migration — v1 `src/` → v2 `audio_to_subs/`

This is the **M0** milestone. Its only goal is to relocate the existing modules into a real package with a `core/` subpackage, **without changing any behaviour**. The acceptance gate is "all existing tests pass unchanged".

## What changes

- `src/` directory is renamed to `audio_to_subs/`.
- Existing pipeline modules move under `audio_to_subs/core/`:
  - `pipeline.py`, `audio_extractor.py`, `audio_splitter.py`, `transcription_client.py`, `subtitle_generator.py`, `config_parser.py`, `logging_config.py`
- `cli.py`, `__main__.py`, `__init__.py` stay at the package root (`audio_to_subs/`).
- All imports are rewritten from `from src.X` to `from audio_to_subs.core.X` (or `from audio_to_subs.X` for `cli`).
- `pyproject.toml` entry point becomes `audio-to-subs = "audio_to_subs.cli:main"`.
- `pyproject.toml` packages config is updated for the new layout.
- Pytest tests use the new import paths; mock targets follow (e.g., `@patch("src.transcription_client.Mistral")` → `@patch("audio_to_subs.core.transcription_client.Mistral")`).

## What does NOT change in M0

- Any module's public API.
- Any module's behaviour or runtime side effects.
- The CLI's flags, help text, exit codes, or progress output.
- Test count or assertions (only the import paths change).
- Dockerfile entrypoint (`python -m audio_to_subs` works the same as `python -m src`).

If a test fails for any reason other than an import path needing update, stop and investigate — that's a bug introduced by the rename, not a v2 design change.

## Mechanical steps

```bash
# 1. Rename the directory.
git mv src audio_to_subs

# 2. Create the core/ subpackage and move pipeline modules into it.
mkdir audio_to_subs/core
git mv audio_to_subs/pipeline.py audio_to_subs/core/pipeline.py
git mv audio_to_subs/audio_extractor.py audio_to_subs/core/audio_extractor.py
git mv audio_to_subs/audio_splitter.py audio_to_subs/core/audio_splitter.py
git mv audio_to_subs/transcription_client.py audio_to_subs/core/transcription_client.py
git mv audio_to_subs/subtitle_generator.py audio_to_subs/core/subtitle_generator.py
git mv audio_to_subs/config_parser.py audio_to_subs/core/config_parser.py
git mv audio_to_subs/logging_config.py audio_to_subs/core/logging_config.py
touch audio_to_subs/core/__init__.py

# 3. Rewrite imports across the package and tests.
# (Run from repo root. Verify the diff before committing.)
find audio_to_subs tests -type f -name "*.py" -exec sed -i \
  -e 's|from src\.pipeline|from audio_to_subs.core.pipeline|g' \
  -e 's|from src\.audio_extractor|from audio_to_subs.core.audio_extractor|g' \
  -e 's|from src\.audio_splitter|from audio_to_subs.core.audio_splitter|g' \
  -e 's|from src\.transcription_client|from audio_to_subs.core.transcription_client|g' \
  -e 's|from src\.subtitle_generator|from audio_to_subs.core.subtitle_generator|g' \
  -e 's|from src\.config_parser|from audio_to_subs.core.config_parser|g' \
  -e 's|from src\.logging_config|from audio_to_subs.core.logging_config|g' \
  -e 's|from src\.cli|from audio_to_subs.cli|g' \
  -e 's|from src import|from audio_to_subs import|g' \
  -e 's|"src\.pipeline"|"audio_to_subs.core.pipeline"|g' \
  -e 's|"src\.audio_extractor"|"audio_to_subs.core.audio_extractor"|g' \
  -e 's|"src\.audio_splitter"|"audio_to_subs.core.audio_splitter"|g' \
  -e 's|"src\.transcription_client"|"audio_to_subs.core.transcription_client"|g' \
  -e 's|"src\.subtitle_generator"|"audio_to_subs.core.subtitle_generator"|g' \
  -e 's|"src\.config_parser"|"audio_to_subs.core.config_parser"|g' \
  -e 's|"src\.logging_config"|"audio_to_subs.core.logging_config"|g' \
  -e 's|"src\.cli"|"audio_to_subs.cli"|g' \
  {} +
```

> **Sanity check**: after running the `sed` block, grep for any surviving `src\.` references and `from src ` lines. Anything left over is either a comment, a docstring, or a missed pattern; fix it by hand.

## Files to edit by hand

### `pyproject.toml`

- `[project.scripts]`: `audio-to-subs = "audio_to_subs.cli:main"`
- `[tool.setuptools.packages.find]`: include `audio_to_subs*` instead of `src*`
- `[tool.coverage.run] source = ["audio_to_subs"]` (was `["src"]`)
- `[tool.mypy]` per-module overrides — rewrite any `src.*` patterns to `audio_to_subs.*`
- `[tool.ruff]` / `[tool.black]` — usually fine; double-check if there are explicit includes

### `.pre-commit-config.yaml` (root + `dev/`)

Both copies use the same hook list. Adjust any `args:` or `files:` patterns that reference `src/`.

### `Dockerfile` and `Dockerfile.dev`

- `COPY src/ /app/src/` → `COPY audio_to_subs/ /app/audio_to_subs/`
- `ENTRYPOINT ["python", "-m", "src"]` → `ENTRYPOINT ["python", "-m", "audio_to_subs"]`
- `HEALTHCHECK CMD python -c "import src.cli"` → `python -c "import audio_to_subs.cli"`

### `docker-compose.yml`

- Any volume mounts that reference `./src` → `./audio_to_subs`.

### `Makefile`

- Test/lint targets that reference `src/` paths.

### `README.md`

- One-line import path update in any "library usage" snippet.

### `.gitignore`

- `__pycache__` patterns under `src/` → `audio_to_subs/`.

## Verification (the M0 acceptance gate)

```bash
# 1. Tests pass unchanged.
pytest

# 2. Lint clean.
black --check audio_to_subs tests
ruff check audio_to_subs tests
mypy --strict audio_to_subs

# 3. CLI still works end-to-end.
audio-to-subs --version
audio-to-subs -i dev/test_video.mp4 -o /tmp/out.srt
diff /tmp/out.srt <(git show HEAD~1:tests/fixtures/expected.srt)   # if such a fixture exists

# 4. Container entrypoint unchanged.
docker build -t a2s:m0 .
docker run --rm -v $(pwd)/dev:/input -v /tmp:/output \
  -e MISTRAL_API_KEY=... a2s:m0 -i /input/test_video.mp4 -o /output/out.srt
```

## Commit hygiene

- One commit for the rename + import rewrite: `refactor: rename src/ to audio_to_subs/ and introduce core/ subpackage`
- A separate commit if any test had to be adjusted beyond mechanical import rewrites — explain why in the body.
- All commits Signed-off-by per the project's commit convention.

After M0 lands, the rest of the v2 milestones can proceed against a clean foundation. No new files are introduced in M0 except `audio_to_subs/core/__init__.py`.
