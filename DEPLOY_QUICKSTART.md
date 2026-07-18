# Deployment quickstart

Two ways to run the stack. Both boot `backend` + `worker` + `frontend` + `redis`.
Both build `backend`/`worker`/`frontend` directly from the GitHub repo at a
pinned tag (`docker-compose.yml` / `docker-compose.docker.yml`'s `build.context`
is a Git URL) — no local clone needed, `up -d --build` alone is enough.

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

## Fronting with HTTPS (Caddy)

Only `frontend` publishes a host port (`8080`) — `backend` and `redis` are
network-internal only, reached over the compose network. Put a
TLS-terminating reverse proxy in front of `frontend`'s `8080` for HTTPS.

A ready-to-use `Caddyfile` is included at the repo root (automatic Let's
Encrypt via a public domain). It's standalone — not wired into either
compose file — so run Caddy separately (host package/binary, or your own
container) on the same host:

```bash
# edit Caddyfile: replace your-domain.example with your real domain
caddy run --config ./Caddyfile
```

Once HTTPS is in front, set `BEHIND_TLS=true` in `.env` (both deployment
paths read it) so the session cookie gets the `Secure` flag, then
recreate the containers.

## Local development builds

Building from the working tree (instead of the pinned GitHub tag) needs the
dev override, which restores a local `build.context`:

```bash
podman compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# or, for the env-file path:
podman compose -f docker-compose.docker.yml -f docker-compose.dev.yml up -d --build
```

## Notes

- `SESSION_SECRET` is generated automatically into the shared `/data` volume on
  first boot — no action needed.
- Bazarr/Sonarr/Radarr are optional and live in `docker-compose.override.yml`
  (auto-included by `docker compose`/`podman compose`). The core app boots
  without them.
- `docker-compose.dev.yml` (local-build override, see above) is **not**
  auto-included — it only applies when passed explicitly via `-f`.
- The full deployment reference lives in `dev/v2/DEPLOYMENT.md`.
