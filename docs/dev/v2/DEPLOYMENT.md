# Deployment

Four containers in `docker-compose.yml`: **backend**, **worker**, **frontend**, **redis**. Two shared volumes: `db_data` (SQLite file) and external `media` volume.

## Image strategy

Backend and worker share single image built from root `Dockerfile`. Frontend is separate image from `frontend/Dockerfile` (Nginx + Vite build). Redis is `redis:7-alpine`.

## Dockerfile (backend + worker)

Multi-stage build: python:3.11-alpine base, installs ffmpeg, libstdc++, ca-certificates. Non-root user (UID 1000). Worker uses sync SQLite driver, backend uses async.

## docker-compose.yml

Services: backend (FastAPI), worker (job processor), frontend (Nginx), redis (pub/sub). SQLite on shared volume. Media volume external: true.

Secrets mounted at `/run/secrets/<name>`. Python code reads `<KEY>` or `<KEY>_FILE` envs, preferring file when present.

Health checks: backend checks `/api/healthz`, redis uses `redis-cli ping`.

## First-run procedure

1. Create external media volume: `docker volume create media`
2. Drop secret files in ./.secrets/ with proper permissions
3. Set env (BAZARR_URL, PATH_MAPPINGS_JSON, ADMIN_USERNAME, FRONTEND_PORT)
4. Bring up: `podman compose up -d`
5. Visit http://localhost:8080 and log in as admin

## Path mapping

Set `PATH_MAPPINGS_JSON` as JSON array: `[["/data/media","/mnt/media"]]`. Multiple pairs supported; first match wins.

## SQLite + multiple writers

WAL + BEGIN IMMEDIATE + busy_timeout=5000 handles 1 API + 1-3 workers safely. Claim SQL portable to Postgres.

**Important**: Any async task acquiring DB session must NOT hold it across await asyncio.sleep() - exit context before waiting.

## Backups

Backup `db_data` volume. Use SQLite `.backup` command for consistent snapshots.