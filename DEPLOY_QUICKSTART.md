# Deployment quickstart

Two ways to run the stack. Both boot `backend` + `worker` + `frontend` + `redis`.

## Option A — Podman secrets (recommended)

Credentials are stored as native Podman secrets. Names are fixed defaults
(`admin_password`, `mistral_api_key`) — they must match these exactly;
podman-compose cannot use a custom name for external secrets.

```bash
echo -n "yourStrongPass!" | podman secret create admin_password -
echo -n "your-mistral-key" | podman secret create mistral_api_key -

podman compose up -d --build
```

Visit http://localhost:8080 and log in as `admin`.

## Option B — Env file (Docker / no secrets)

Supply credentials via a plaintext `.env` instead of secrets. Copy
`.env.example`, set `ADMIN_PASSWORD` and `MISTRAL_API_KEY`, then run the
standalone env-file compose file (do **not** merge it with
`docker-compose.yml` — use it on its own; `docker-compose.override.yml` is
auto-included by both engines):

```bash
cp .env.example .env          # edit ADMIN_PASSWORD / MISTRAL_API_KEY
docker compose -f docker-compose.docker.yml up -d --build
```

This path can be used in place of Podman secrets. (Under Podman you can
validate the same mechanism with `podman compose -f docker-compose.docker.yml
up -d --build`.)

## Notes

- `SESSION_SECRET` is generated automatically into the shared `/data` volume on
  first boot — no action needed.
- Bazarr/Sonarr/Radarr are optional and live in `docker-compose.override.yml`
  (auto-included by `docker compose`/`podman compose`). The core app boots
  without them.
- The full deployment reference lives in `dev/v2/DEPLOYMENT.md`.
