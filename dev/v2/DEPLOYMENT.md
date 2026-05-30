# v2 — Deployment

Four containers in `docker-compose.yml`: **backend**, **worker**, **frontend**, **redis**. Two shared volumes: `db_data` (SQLite file) and an external `media` volume (the same mount Bazarr uses).

## Image strategy

- Backend and worker **share a single image** built from the existing root `Dockerfile` (adapted from v1's Alpine + Python 3.11 multi-stage build). They differ only in `command:`.
- Frontend is its own image built from `frontend/Dockerfile` (Nginx + Vite build output).
- Redis is `redis:7-alpine`.

## `Dockerfile` (backend + worker)

Minimal diff from v1:

```dockerfile
# Build stage — install deps into /install
FROM python:3.11-alpine AS builder
RUN apk add --no-cache build-base libffi-dev openssl-dev
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Runtime
FROM python:3.11-alpine
RUN apk add --no-cache ffmpeg libstdc++ ca-certificates
COPY --from=builder /install /usr/local
WORKDIR /app
COPY audio_to_subs/ /app/audio_to_subs/
COPY pyproject.toml /app/

# Non-root user
ARG USER_UID=1000
ARG USER_GID=1000
RUN addgroup -g ${USER_GID} app && adduser -D -u ${USER_UID} -G app app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import audio_to_subs.api.app" || exit 1

# Default command runs the API; the worker service overrides this.
CMD ["uvicorn", "audio_to_subs.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

## `docker-compose.yml`

```yaml
services:
  backend:
    build: .
    command: ["uvicorn", "audio_to_subs.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
    environment:
      DATABASE_URL: "sqlite+aiosqlite:////data/audio-to-subs.db"
      REDIS_URL: "redis://redis:6379/0"
      MISTRAL_API_KEY_FILE: "/run/secrets/mistral_api_key"
      BAZARR_URL: "${BAZARR_URL}"
      BAZARR_API_KEY_FILE: "/run/secrets/bazarr_api_key"
      SESSION_SECRET_FILE: "/run/secrets/session_secret"
      ADMIN_USERNAME: "${ADMIN_USERNAME:-admin}"
      ADMIN_PASSWORD_FILE: "/run/secrets/admin_password"
      PATH_MAPPINGS_JSON: '${PATH_MAPPINGS_JSON:-[]}'
    volumes:
      - db_data:/data
      - media:/mnt/media
    secrets:
      - mistral_api_key
      - bazarr_api_key
      - session_secret
      - admin_password
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:8000/api/healthz | grep -q '\"db\"'"]
      interval: 30s
      timeout: 5s
      retries: 3

  worker:
    build: .
    command: ["python", "-m", "audio_to_subs.worker"]
    environment:
      # Same env as backend; YAML anchors keep this DRY in real file.
      DATABASE_URL: "sqlite:////data/audio-to-subs.db"
      REDIS_URL: "redis://redis:6379/0"
      MISTRAL_API_KEY_FILE: "/run/secrets/mistral_api_key"
      PATH_MAPPINGS_JSON: '${PATH_MAPPINGS_JSON:-[]}'
    volumes:
      - db_data:/data
      - media:/mnt/media
    secrets: [mistral_api_key]
    depends_on:
      backend:
        condition: service_started
      redis:
        condition: service_healthy
    deploy:
      replicas: 1
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports:
      - "${FRONTEND_PORT:-8080}:80"
    depends_on:
      backend:
        condition: service_started
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

volumes:
  db_data:
  media:
    external: true

secrets:
  mistral_api_key:
    file: ./.secrets/mistral_api_key
  bazarr_api_key:
    file: ./.secrets/bazarr_api_key
  session_secret:
    file: ./.secrets/session_secret
  admin_password:
    file: ./.secrets/admin_password
```

Notes:

- The `worker` uses the sync SQLite driver (`sqlite:////…`), the backend uses async (`sqlite+aiosqlite:////…`). Both point at the same file.
- The `media` volume is declared `external: true` — the operator creates it once with `docker volume create media` (or names the existing Bazarr volume here). This is the **only** point where `audio-to-subs` and Bazarr share state on disk.
- Redis runs without persistence (`--save "" --appendonly no`). SQLite is the source of truth.
- Secrets are mounted at `/run/secrets/<name>`. The Python code reads either `<KEY>` or `<KEY>_FILE` envs, preferring the file when present.

## First-run procedure

```bash
# 1. Create the external media volume (or alias an existing one)
docker volume create media

# 2. Drop secret files in ./.secrets/
mkdir -p .secrets && chmod 700 .secrets
echo "your-mistral-key"  > .secrets/mistral_api_key
echo "your-bazarr-key"   > .secrets/bazarr_api_key
openssl rand -hex 32     > .secrets/session_secret
echo "yourStrongPass!"   > .secrets/admin_password
chmod 600 .secrets/*

# 3. Set env (or write to .env next to docker-compose.yml)
export BAZARR_URL="http://bazarr.lan:6767"
export PATH_MAPPINGS_JSON='[["/data/media","/mnt/media"]]'
export ADMIN_USERNAME="admin"
export FRONTEND_PORT=8080

# 4. Bring up
docker compose up -d

# 5. Visit http://localhost:8080 and log in as admin.
```

## Path mapping

If Bazarr reports `/data/media/Movies/Movie (2023)/Movie.mkv` but in the worker container that file is at `/mnt/media/Movies/Movie (2023)/Movie.mkv`, set:

```
PATH_MAPPINGS_JSON=[["/data/media","/mnt/media"]]
```

Multiple pairs are supported; first match wins. See [`BAZARR_INTEGRATION.md`](BAZARR_INTEGRATION.md).

## SQLite + multiple writers — should you worry?

Short answer: not for a homelab personal tool with 1–3 workers.

- WAL mode lets readers (the API) read concurrently with one writer (a worker or the API).
- The only write hotspot is the **claim** statement, which is a single `UPDATE … RETURNING` inside `BEGIN IMMEDIATE` with `busy_timeout=5000`. N workers serialise on this safely.
- Reaper writes (every 60 s) are tiny.

When to migrate to Postgres:

- More than ~3 concurrent workers.
- Multiple backend replicas behind a load balancer.
- Any failure pattern that traces back to `database is locked`.

Migration cost: one DSN change + `alembic upgrade head` against the new DB. The codebase deliberately uses no SQLite-only SQL.

## Logs & monitoring

- Container logs go to stdout/stderr (FastAPI default + the worker's `logging`).
- `dev/v2` doesn't prescribe a metrics stack. If needed later: `prometheus-fastapi-instrumentator` on the API, `redis_exporter`, the SQLite size in a side-car cron.

## Backups

- The whole `db_data` volume is one SQLite file. Back it up with `docker run --rm -v audio-to-subs_db_data:/data -v $PWD:/out alpine sh -c 'cp /data/audio-to-subs.db /out/db-$(date +%F).db'` (use `.backup` SQLite command in production to get a consistent snapshot).
- Secrets are external by definition. The `.secrets/` directory should be in a password manager or vault, not in git.
