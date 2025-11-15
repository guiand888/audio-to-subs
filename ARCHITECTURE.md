# audio-to-subs Architecture

## Overview

**audio-to-subs** is a Python-based CLI tool that automates the conversion of video audio to subtitle files using AI-powered transcription.

### Pipeline Flow

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌─────────────┐
│ Video Input │────>│ Audio Extract│────>│ AI Transcribe  │────>│ SRT Generate│
│  (.mp4/mkv) │     │   (FFmpeg)   │     │ (Mistral API)  │     │   (.srt)    │
└─────────────┘     └──────────────┘     └────────────────┘     └─────────────┘
```

## Why Python?

- Strong multimedia processing ecosystem (ffmpeg-python, pydub)
- Native API client libraries for Mistral AI
- Robust SRT manipulation libraries
- Excellent CLI frameworks (Click/argparse)
- Strong testing support for TDD/BDD (pytest, pytest-bdd)

## Core Components

### 1. Audio Extractor (`audio_extractor.py`)

**Responsibility**: Extract audio tracks from video files

**Implementation**:
- Tool: FFmpeg via subprocess or ffmpeg-python wrapper
- Output: Temporary audio file (format TBD based on Mistral API requirements)
- Error handling: Invalid formats, missing FFmpeg, corrupt videos

**Key Functions**:
- `extract_audio(video_path: Path, output_path: Path) -> Path`
- `validate_video_file(video_path: Path) -> bool`
- `check_ffmpeg_available() -> bool`

### 2. Transcription Client (`transcription_client.py`)

**Responsibility**: Interface with Mistral AI transcription API

**Configuration**:
- Endpoint: `audio/transcriptions`
- Model: `voxtral-mini-latest` (Voxtral Mini Transcribe) - configurable
- Documentation: https://docs.mistral.ai/capabilities/audio_transcription#transcription
- Max audio length: 15 minutes (900 seconds) - auto-split longer files

**Features**:
- Configurable model name (default: voxtral-mini-latest per Mistral docs)
- Optional language parameter for improved accuracy
- Automatic audio splitting for files > 15 minutes
- Retry pattern with exponential backoff (max 3 attempts)
- Rate limiting awareness
- Secure API key management via environment variables
- Timestamp extraction from API response

**Key Functions**:
- `transcribe_audio(audio_path: Path, language: Optional[str] = None) -> Transcription`
- `transcribe_audio_with_timestamps(audio_path: Path, language: Optional[str] = None) -> List[Dict]`
- `validate_api_key() -> bool`
- `_retry_with_backoff(func, max_retries: int = 3) -> Any`

**Data Models**:
```python
@dataclass
class TranscriptionSegment:
    start_time: float
    end_time: float
    text: str

@dataclass
class Transcription:
    segments: List[TranscriptionSegment]
    language: str
    duration: float
```

### 3. Subtitle Generator (`subtitle_generator.py`)

**Responsibility**: Convert transcription data to SRT format

**SRT Format Specification**:
```
1
00:00:00,000 --> 00:00:02,500
First subtitle text

2
00:00:02,500 --> 00:00:05,000
Second subtitle text
```

**Features**:
- Timestamp formatting (HH:MM:SS,mmm)
- Text segmentation (max characters per line: ~42-50)
- Multi-line subtitle support
- UTF-8 encoding

**Key Functions**:
- `generate_srt(transcription: Transcription, output_path: Path) -> Path`
- `format_timestamp(seconds: float) -> str`
- `segment_text(text: str, max_chars: int = 42) -> List[str]`

### 4. Pipeline Orchestrator (`pipeline.py`)

**Responsibility**: Coordinate the entire workflow

**Features**:
- Temporary file management and cleanup
- Progress reporting
- Batch processing support
- Error recovery and logging
- Resource cleanup on failure

**Key Functions**:
- `process_video(video_path: Path, output_dir: Path, api_key: str, transcription_model: str = "voxtral-mini-latest", language: Optional[str] = None) -> Path`
- `process_batch(video_paths: List[Path], output_dir: Path, api_key: str) -> List[Path]`
- `cleanup_temp_files(temp_dir: Path) -> None`

**Workflow**:
1. Validate input video file
2. Extract audio to temporary file
3. Check audio duration; split if > 15 minutes
4. Transcribe audio via Mistral API (with optional language)
5. Merge transcriptions from multiple segments if needed
6. Generate SRT file in selected format
7. Clean up temporary audio files
8. Return path to generated subtitle

### 5. Audio Splitter (`audio_splitter.py`)

**Responsibility**: Split audio files exceeding 15-minute Mistral API limit

**Features**:
- Automatic duration detection using ffprobe
- Segment splitting with 2-second overlap for context preservation
- Returns list of split audio files or original if under limit

**Key Functions**:
- `get_audio_duration(audio_path: str) -> float`
- `split_audio(audio_path: str, output_dir: str, max_length: int = 900) -> List[str]`
- `needs_splitting(audio_path: str, max_length: int = 900) -> bool`

### 6. CLI Interface (`cli.py` / `__main__.py`)

**Responsibility**: User interaction and command-line interface

**Framework**: Click (preferred for elegance and features)

**Arguments**:
- `--input, -i`: Video file path(s) (required)
- `--output, -o`: Output directory (default: same as input)
- `--format, -f`: Subtitle format: srt, vtt, webvtt, sbv (default: srt)
- `--api-key`: Mistral API key (default: `MISTRAL_API_KEY` env var)
- `--language, -l`: Language hint for transcription (optional, e.g., 'en', 'fr')
- `--model, -m`: Transcription model (default: voxtral-mini-latest)
- `--config`: Configuration file for batch processing
- `--progress`: Show detailed progress (audio upload, transcription segments)
- `--quiet, -q`: Suppress all text output (silent mode)
- `--before-exec`: Script or command to run before processing starts
- `--after-exec`: Script or command to run after successful completion
- `--debug`: Debug mode with detailed logging

**Example Usage**:
```bash
# Single file
audio-to-subs -i video.mp4

# With custom output directory
audio-to-subs -i video.mp4 -o ./subtitles/

# Batch processing
audio-to-subs -i video1.mp4 video2.mp4 video3.mp4

# With language hint
audio-to-subs -i video.mp4 -l en
```

## Project Structure

```
audio-to-subs/
├── src/
│   ├── __init__.py
│   ├── __main__.py                  # Entry point
│   ├── cli.py                       # CLI interface
│   ├── pipeline.py                  # Orchestration
│   ├── audio_extractor.py           # FFmpeg wrapper
│   ├── audio_splitter.py            # Audio splitting for >15min files
│   ├── transcription_client.py      # Mistral API client
│   ├── subtitle_generator.py        # Subtitle generation
│   ├── config_parser.py             # Configuration file parsing
│   └── audio_to_subs/               # Package directory
│       └── (legacy, deprecated)
├── tests/
│   ├── __init__.py
│   ├── test_audio_extractor.py
│   ├── test_transcription_client.py
│   ├── test_subtitle_generator.py
│   ├── test_pipeline.py
│   ├── test_cli.py
│   └── fixtures/                    # Sample audio/video/SRT files
├── features/                        # BDD scenarios (Gherkin)
│   └── audio_to_subs.feature
├── .env.example                     # API key template
├── .gitignore
├── requirements.txt                 # Production dependencies
├── requirements-dev.txt             # Development/testing dependencies
├── pyproject.toml                   # Modern Python packaging
├── README.md
├── ARCHITECTURE.md                  # This file
├── LICENSE                          # GPLv3
└── WARP.md
```

## Deployment Model

**Container-First Architecture**: This application is exclusively packaged and deployed as a container.

### Container Technology
- **Base Image**: Alpine Linux (minimal footprint)
- **Build Tool**: Podman (Docker-compatible)
- **Orchestration**: Docker Compose / Podman Compose
- **Production**: Kubernetes-ready

### Development Environment
- **Developer Workstation**: No local Python/dependencies installation
- **All development**: Inside containers
- **Testing**: Containerized test execution
- **Secret Management**: Podman secrets (not environment variables in production)

## Dependencies

### Core Dependencies
```
mistralai>=0.0.7       # Official Mistral AI client
ffmpeg-python>=0.2.0   # FFmpeg wrapper
click>=8.1.0           # CLI framework
```

### Development Dependencies
```
pytest>=7.0.0          # Testing framework
pytest-bdd>=6.0.0      # BDD support
pytest-cov>=4.0.0      # Coverage reporting
pytest-mock>=3.10.0    # Mocking utilities
responses>=0.23.0      # HTTP request mocking
black>=23.0.0          # Code formatting
ruff>=0.1.0            # Fast Python linter
mypy>=1.0.0            # Type checking
```

### Container System Dependencies
- FFmpeg (installed in container image)
- Python 3.9+ (Alpine-based)
- Alpine Linux base packages

## Development Methodology

### Test-Driven Development (TDD)

**Red-Green-Refactor Cycle**:
1. **Red**: Write a failing test
2. **Green**: Write minimal code to pass the test
3. **Refactor**: Improve code quality without changing behavior

**Test Coverage Requirements**:
- Minimum 80% code coverage
- 100% coverage for critical paths (API calls, file I/O)
- All edge cases covered

### Behavior-Driven Development (BDD)

**Gherkin Scenarios** define acceptance criteria before implementation.

**Example Feature**:
```gherkin
Feature: Video to Subtitle Conversion
  As a user
  I want to convert video audio to subtitles
  So that I can add captions to my videos

  Scenario: Convert single video file to SRT
    Given a video file "sample.mp4"
    And a valid Mistral API key
    When I run the conversion
    Then an SRT file "sample.srt" should be created
    And the SRT should contain timestamped text
    And the timestamps should match the audio duration

  Scenario: Handle missing API key
    Given a video file "sample.mp4"
    And no API key is configured
    When I run the conversion
    Then I should see an error message about missing API key
    And no SRT file should be created
```

### Development Phases

#### Phase 1: Setup & BDD (Days 1-2)
- Project structure setup
- BDD feature files
- Development environment configuration
- CI/CD pipeline skeleton

#### Phase 2: Core Components (Days 2-5)
**TDD approach for each component**:

1. **Audio Extractor**
   - Test: Extract audio from sample video
   - Test: Handle missing FFmpeg
   - Test: Handle corrupt/invalid video files
   - Test: Support multiple video formats

2. **Transcription Client**
   - Test: Mock successful API transcription
   - Test: Retry on transient failures
   - Test: Handle API errors gracefully
   - Test: Secure API key handling
   - Test: Parse timestamp data correctly

3. **Subtitle Generator**
   - Test: Format timestamps correctly
   - Test: Generate valid SRT structure
   - Test: Handle edge cases (empty transcription)
   - Test: Text segmentation for readability

4. **Pipeline Orchestrator**
   - Test: End-to-end integration (mocked API)
   - Test: Temporary file cleanup
   - Test: Error propagation
   - Test: Batch processing

#### Phase 3: Integration & Polish (Days 5-7)
- Real Mistral API integration testing
- Sample video processing validation
- Performance optimization
- Documentation completion
- README with usage examples

## Container Architecture

### Dockerfile Structure

**Multi-stage build** for minimal production image:

1. **Builder Stage**: Install build dependencies, compile Python packages
2. **Runtime Stage**: Minimal Alpine image with only runtime requirements

**Key Considerations**:
- Alpine Linux base for minimal size (~50MB base)
- FFmpeg installed from Alpine repositories
- Non-root user for security
- Volume mounts for video input/output
- Health checks for container orchestration

### Docker Compose / Podman Compose

**Services**:
- `audio-to-subs`: Main application container

**Volumes**:
- Input videos (bind mount or volume)
- Output subtitles (bind mount or volume)
- Temporary processing space (tmpfs for performance)

**Secrets** (Podman secrets preferred):
- `mistral_api_key`: Mistral AI API key

### Build and Run

```bash
# Build image with Podman
podman build -t audio-to-subs:latest .

# Run with Podman
podman run --rm \
  --secret mistral_api_key \
  -v ./videos:/input:ro \
  -v ./subtitles:/output \
  audio-to-subs:latest -i /input/video.mp4 -o /output

# Or with Podman Compose
podman-compose up
```

### Kubernetes Deployment

**Resources**:
- Deployment with configurable replicas
- ConfigMap for configuration
- Secret for API key
- PersistentVolumeClaim for video storage
- Job/CronJob for batch processing

## Security & Best Practices

### Security Considerations

1. **API Key Management**
   - **Production**: Use Podman secrets (never environment variables)
   - **Development**: Podman secrets or .env file (not committed)
   - Never commit API keys to version control
   - Validate key before processing

2. **Input Validation**
   - Check file types and extensions
   - Validate file sizes (prevent resource exhaustion)
   - Sanitize file paths (prevent directory traversal)

3. **Container Security**
   - Run as non-root user (UID 1000)
   - Read-only root filesystem where possible
   - Drop unnecessary capabilities
   - Use minimal Alpine base image
   - Regular security updates for base image

4. **Temporary Files**
   - Use container tmpfs for temporary audio files
   - Clean up after processing (even on failure)
   - Set appropriate file permissions
   - Automatic cleanup on container restart

4. **Dependencies**
   - Pin dependency versions in requirements.txt
   - Regular security audits with `pip-audit`
   - Keep dependencies updated

### Resilience Patterns

1. **Retry Pattern**
   - Exponential backoff for API calls
   - Maximum 3 retry attempts
   - Retry only on transient errors (5xx, network timeout)

2. **Circuit Breaker** (Future Enhancement)
   - Not required for MVP (single-user CLI tool)
   - Consider for multi-user deployments

3. **Graceful Degradation**
   - Continue batch processing on single file failure
   - Log errors without crashing entire pipeline
   - Provide partial results when possible

4. **Comprehensive Logging**
   - Structured logging (JSON format option)
   - Log levels: DEBUG, INFO, WARNING, ERROR
   - File and console logging support

### Clean Code Principles

- **PEP 8 compliance**: Enforced by Black and Ruff
- **Type hints**: Required for all public functions
- **Docstrings**: Google-style for all modules and public functions
- **Small functions**: Max 20-30 lines per function
- **DRY principle**: No code duplication
- **Meaningful names**: Self-documenting code

## Error Handling Strategy

### Error Categories

1. **User Errors** (Exit code 1)
   - Invalid input file
   - Missing API key
   - Invalid configuration

2. **System Errors** (Exit code 2)
   - FFmpeg not found
   - Disk space issues
   - Permission errors

3. **API Errors** (Exit code 3)
   - Authentication failures
   - Rate limiting
   - Service unavailable

4. **Unexpected Errors** (Exit code 99)
   - Unhandled exceptions
   - Programming errors

### Error Messages

- **User-friendly**: Clear, actionable messages
- **Contextual**: Include file names, line numbers
- **Helpful**: Suggest solutions when possible
- **Logged**: All errors logged with full stack traces

## Performance Considerations

### Optimization Targets

- Process 1-hour video in < 5 minutes (excluding API time)
- Memory usage < 500MB for typical video
- Batch processing: parallel API calls (future enhancement)

### Bottlenecks

1. **Audio Extraction**: I/O bound, fast with FFmpeg
2. **API Transcription**: Network bound, slowest step
3. **SRT Generation**: CPU bound, negligible time

### Future Optimizations

- Parallel processing for batch mode
- Audio chunking for very long videos
- Caching of transcriptions
- Local model support (Whisper) as alternative to API

## Testing Strategy

### Unit Tests
- Each component tested in isolation
- Mocked external dependencies (API, FFmpeg)
- Fast execution (< 5 seconds total)

### Integration Tests
- Components tested together
- Mocked Mistral API responses
- Temporary file handling validated

### End-to-End Tests
- Real video file processing
- Mocked API (avoid costs)
- Validate complete workflow

### Manual Testing Checklist
- [ ] Real Mistral API call with sample video
- [ ] Various video formats (.mp4, .mkv, .avi)
- [ ] Large video files (> 1 hour)
- [ ] Multiple languages
- [ ] Batch processing
- [ ] Error scenarios (no API key, invalid file, etc.)

## Monitoring & Observability

### Logging Strategy
- **Development**: Console logging, DEBUG level
- **Production**: File logging, INFO level
- **Format**: Structured JSON for parsing

### Metrics to Track
- Processing time per video
- API response times
- Error rates by category
- File size distributions

## Future Enhancements

### Short-term (v1.1-1.2)
- Support for additional subtitle formats (VTT, ASS)
- Language auto-detection
- Custom SRT formatting options
- Progress bars for long operations

### Medium-term (v1.3-2.0)
- Local transcription with Whisper model (offline mode)
- GUI wrapper (Electron/PyQt)
- Subtitle editing capabilities
- Translation support (multi-language subtitles)

### Long-term (v2.0+)
- Web service deployment
- Batch processing API
- Speaker diarization
- Subtitle quality scoring

## Contributing Guidelines

### Development Workflow
1. Create feature branch from `main`
2. Write BDD scenario (if applicable)
3. Write failing tests (TDD)
4. Implement feature
5. Ensure all tests pass
6. Run linters (black, ruff, mypy)
7. Update documentation
8. Submit pull request
9. Code review required
10. Merge after approval
11. Delete feature branch

### Commit Message Format
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**: feat, fix, docs, test, refactor, style, chore

**Example**:
```
feat(transcription): add retry logic for API calls

Implement exponential backoff for transient failures.
Max 3 retries with 1s, 2s, 4s delays.

Closes #15
```

## License

GPLv3 - All code must comply with license requirements.

---

**Document Version**: 1.0  
**Last Updated**: 2025-11-15  
**Maintainer**: Guillaume Andre (@guiand888)
