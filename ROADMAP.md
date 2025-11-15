# audio-to-subs Implementation Roadmap

## Phase 1: Project Foundation (Days 1-2)

### Step 1: Project Structure Setup
- [x] Create ARCHITECTURE.md
- [x] Create ROADMAP.md
- [ ] Create project directory structure
- [ ] Initialize pyproject.toml with metadata
- [ ] Create requirements.txt and requirements-dev.txt
- [ ] Create .env.example
- [ ] Update .gitignore for Python
- [ ] Initialize git repository structure

### Step 2: BDD Foundation
- [ ] Create features/ directory
- [ ] Write audio_to_subs.feature with core scenarios:
  - Convert single video to SRT
  - Handle missing API key
  - Handle invalid video file
  - Batch processing multiple videos
- [ ] Set up pytest-bdd configuration

### Step 3: Container Development Environment
- [ ] Create Dockerfile.dev (development container)
- [ ] Create Dockerfile (production container)
- [ ] Create docker-compose.yml (Podman Compose compatible)
- [ ] Create Makefile (container command shortcuts)
- [ ] Build development container
- [ ] Verify FFmpeg in container
- [ ] Test pytest execution in container
- [ ] Test code quality tools in container

## Phase 2: Core Components (Days 2-5)

### Step 4: Audio Extractor (TDD)
**Test file**: `tests/test_audio_extractor.py`

- [ ] Test: check_ffmpeg_available() returns True/False
- [ ] Test: validate_video_file() accepts valid formats
- [ ] Test: validate_video_file() rejects invalid formats
- [ ] Test: extract_audio() creates audio file
- [ ] Test: extract_audio() handles missing FFmpeg
- [ ] Test: extract_audio() handles corrupt video

**Implementation file**: `src/audio_to_subs/audio_extractor.py`

### Step 5: Transcription Client (TDD)
**Test file**: `tests/test_transcription_client.py`

- [ ] Test: validate_api_key() checks env variable
- [ ] Test: transcribe_audio() with mocked API success
- [ ] Test: transcribe_audio() returns Transcription object
- [ ] Test: retry logic on transient failures (5xx errors)
- [ ] Test: no retry on permanent failures (4xx errors)
- [ ] Test: parse timestamp data correctly from API response

**Implementation file**: `src/audio_to_subs/transcription_client.py`

### Step 6: Subtitle Generator (TDD)
**Test file**: `tests/test_subtitle_generator.py`

- [ ] Test: format_timestamp() converts seconds to SRT format
- [ ] Test: format_timestamp() handles edge cases (0, 3600, etc.)
- [ ] Test: generate_srt() creates valid SRT structure
- [ ] Test: generate_srt() handles empty transcription
- [ ] Test: generate_srt() uses UTF-8 encoding
- [ ] Test: segment_text() splits long lines appropriately

**Implementation file**: `src/audio_to_subs/subtitle_generator.py`

### Step 7: Pipeline Orchestrator (TDD)
**Test file**: `tests/test_pipeline.py`

- [ ] Test: process_video() end-to-end (mocked API)
- [ ] Test: cleanup_temp_files() removes temporary audio
- [ ] Test: cleanup occurs even on failure
- [ ] Test: process_batch() handles multiple videos
- [ ] Test: process_batch() continues on single file failure

**Implementation file**: `src/audio_to_subs/pipeline.py`

### Step 8: CLI Interface (TDD)
**Test file**: `tests/test_cli.py`

- [ ] Test: CLI accepts required arguments
- [ ] Test: CLI uses MISTRAL_API_KEY env var by default
- [ ] Test: CLI validates input file exists
- [ ] Test: CLI creates output directory if missing
- [ ] Test: CLI handles verbose/debug flags

**Implementation file**: `src/audio_to_subs/cli.py` and `__main__.py`

## Phase 3: Integration & Polish (Days 5-7)

### Step 9: Integration Testing
- [ ] Run BDD scenarios with mocked API
- [ ] Verify all scenarios pass
- [ ] Test with real Mistral API (sample video)
- [ ] Test multiple video formats (.mp4, .mkv, .avi)
- [ ] Test error scenarios (no API key, invalid files)

### Step 10: Documentation
- [ ] Write comprehensive README.md:
  - Installation instructions
  - FFmpeg setup guide
  - API key configuration
  - Usage examples
  - Troubleshooting section
- [ ] Add docstrings to all public functions
- [ ] Create CONTRIBUTING.md
- [ ] Update WARP.md with project-specific guidance

### Step 11: Quality Assurance
- [ ] Run pytest with coverage (target: >80%)
- [ ] Run black (code formatting)
- [ ] Run ruff (linting)
- [ ] Run mypy (type checking)
- [ ] Fix all warnings and errors

### Step 12: Packaging
- [ ] Test installation with pip install -e .
- [ ] Verify CLI command works: audio-to-subs --help
- [ ] Test in clean virtual environment
- [ ] Prepare for PyPI (future)

## Phase 4: Enhanced Features (Planned)

### Step 13: Progress Reporting
**Status**: In Development

- [ ] Implement `--progress` flag for detailed progress reporting
- [ ] Track audio upload progress (bytes sent / total bytes)
- [ ] Show segment transcription progress (Segment X of Y)
- [ ] Update progress callback mechanism in Pipeline
- [ ] Extend TranscriptionClient to report upload progress
- [ ] Tests: Verify progress callbacks are triggered

### Step 14: Silent Mode
**Status**: Planned

- [ ] Implement `--quiet` flag for silent operation
- [ ] Suppress all stdout output when enabled
- [ ] Preserve error logging (stderr only)
- [ ] Useful for scripting and automation

**Implementation**:
- Add conditional output wrapping in CLI
- Progress callback becomes no-op when quiet mode active
- Errors still reported to stderr

### Step 15: Hook Scripts
**Status**: Planned

- [ ] Implement `--before-exec` flag (pre-run hook)
  - Execute script/command before processing starts
  - Exit with error if script fails
  - Use case: Validate environment, create directories, etc.

- [ ] Implement `--after-exec` flag (post-run hook)
  - Execute script/command after successful completion
  - Has access to output file path via environment variable
  - Exit code doesn't affect overall success (informational only)
  - Use case: Copy files, send notifications, cleanup, etc.

**Implementation**:
- CLI accepts command string for both flags
- Parse and execute via subprocess.run()
- Set AUDIO_TO_SUBS_OUTPUT env var in after-exec context
- Proper error handling and reporting
- Tests: Mock subprocess, verify execution and error handling

## Immediate Next Steps (Oscar Mike!)

### 1. ✅ Create Project Structure
```bash
mkdir -p src/audio_to_subs tests/fixtures features
touch src/audio_to_subs/{__init__.py,__main__.py,cli.py,pipeline.py,audio_extractor.py,transcription_client.py,subtitle_generator.py}
touch tests/{__init__.py,test_audio_extractor.py,test_transcription_client.py,test_subtitle_generator.py,test_pipeline.py,test_cli.py}
touch features/audio_to_subs.feature
touch .env.example
```

### 2. ✅ Create pyproject.toml
Modern Python packaging with project metadata, dependencies, and tool configurations.

### 3. ✅ Create requirements files
- requirements.txt (production)
- requirements-dev.txt (testing/development)

### 4. ✅ Update .gitignore
Python-specific ignores: __pycache__, *.pyc, .env, venv/, .pytest_cache/, etc.

### 5. ✅ Write First BDD Scenario
Define the happy path: convert video to SRT with valid API key.

### 6. Create Container Infrastructure
- Dockerfile.dev (Alpine-based development container)
- Dockerfile (Alpine-based production container with multi-stage build)
- docker-compose.yml (Podman Compose compatible)
- Makefile (shortcuts for common Podman commands)
- .dockerignore

### 7. Start TDD Cycle (Containerized)
Begin with audio_extractor.py - simplest component with clear responsibilities.
All tests run inside development container.

## Success Criteria

### MVP (v1.0) ✅ COMPLETE
- [x] Convert single video file to SRT
- [x] Support common formats (.mp4, .mkv, .avi)
- [x] Handle errors gracefully
- [x] Clean, documented code
- [x] >80% test coverage (85 tests passing)
- [x] CLI works as documented
- [x] Batch processing for multiple videos
- [x] Multiple output formats (SRT, VTT, WebVTT, SBV)
- [x] Configuration file support

### Quality Gates ✅ MET
- [x] All tests pass (pytest): 85 passed, 3 skipped
- [x] No critical linting errors (ruff)
- [x] Type hints updated (Python 3.9+)
- [x] Code formatted (black)
- [x] Documentation complete (README, QUALITY.md, docstrings)
- [x] BDD scenarios ready

## Timeline Estimate

**Total: 5-7 days**

- Day 1-2: Setup, BDD scenarios, audio extractor
- Day 3-4: Transcription client, subtitle generator
- Day 5: Pipeline, CLI, integration
- Day 6-7: Testing, documentation, polish

---

**Status**: Ready to begin Phase 1, Step 1  
**Next Action**: Create project structure  
**Updated**: 2025-11-15
