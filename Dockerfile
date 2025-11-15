# Multi-stage build for minimal production image

# Build arguments for user configuration
ARG USER_UID=1000
ARG USER_GID=1000

# Stage 1: Builder
FROM python:3.11-alpine AS builder

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    linux-headers

# Set working directory
WORKDIR /build

# Copy dependency files
COPY requirements.txt ./

# Install dependencies to temporary location
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Copy application source
COPY src/ ./src/
COPY pyproject.toml ./

# Install application
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM python:3.11-alpine

# Build arguments for user configuration
ARG USER_UID=1000
ARG USER_GID=1000

# Install only runtime dependencies
RUN apk add --no-cache \
    ffmpeg \
    libstdc++

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ /app/src/
COPY pyproject.toml /app/

# Set working directory
WORKDIR /app

# Create non-root user with configurable UID/GID
RUN addgroup -g ${USER_GID} appgroup && \
    adduser -D -u ${USER_UID} -G appgroup appuser && \
    chown -R appuser:appgroup /app

# Create directories for input/output
RUN mkdir -p /input /output /tmp/audio-to-subs && \
    chown -R appuser:appgroup /input /output /tmp/audio-to-subs

USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TMPDIR=/tmp/audio-to-subs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from src import cli; print('OK')" || exit 1

# Entry point
ENTRYPOINT ["python", "-m", "src"]

# Default arguments
CMD ["--help"]
