# Multi-stage build for minimal production image

# Build arguments for user configuration
ARG USER_UID=1000
ARG USER_GID=1000

# Application version (single source of truth: repo-root VERSION / .env
# APP_VERSION, passed as a compose build arg). Baked into the image below so
# audio_to_subs.__version__ and GET /api/version report the running release.
ARG APP_VERSION=unknown

# Stage 1: Builder
FROM docker.io/library/python:3.11.9-alpine3.19 AS builder

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    linux-headers \
    ca-certificates

# Set working directory
WORKDIR /build

# Copy dependency files
COPY requirements.txt ./

# Install dependencies to temporary location
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Copy application source
COPY audio_to_subs/ ./audio_to_subs/
COPY pyproject.toml ./

# Install application
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM docker.io/library/python:3.11.9-alpine3.19

# Build arguments for user configuration
ARG USER_UID=1000
ARG USER_GID=1000

# Re-declare in this stage (ARGs before the first FROM aren't inherited) and
# persist as an env var so the app reads it at runtime.
ARG APP_VERSION=unknown
ENV APP_VERSION=${APP_VERSION}

# Install only runtime dependencies
RUN apk add --no-cache \
    ffmpeg \
    libstdc++ \
    ca-certificates \
    # For uvicorn
    libc6-compat

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY audio_to_subs/ /app/audio_to_subs/
COPY pyproject.toml alembic.ini /app/

# Set working directory
WORKDIR /app

# Create non-root user with configurable UID/GID
RUN addgroup -g ${USER_GID} appgroup && \
    adduser -D -u ${USER_UID} -G appgroup appuser && \
    chown -R appuser:appgroup /app

# Create directories for input/output, plus placeholders for named-volume
# mount points (/data, /movies, /tv) so a fresh empty volume mounted over
# them inherits appuser ownership instead of the root:root default Docker/
# Podman assign to newly created mount points.
RUN mkdir -p /input /output /tmp/parolesub /data /movies /tv && \
    chown -R appuser:appgroup /input /output /tmp/parolesub /data /movies /tv

USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TMPDIR=/tmp/parolesub

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from audio_to_subs.api.app import app; print('OK')" || exit 1

# Entry point for backend (API mode)
ENTRYPOINT ["uvicorn", "audio_to_subs.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

# Default arguments (can be overridden)
CMD []
