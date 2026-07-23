# Authentication

Single admin user. Multi-user-ready schema (`users` table can hold N rows), but bootstrap creates exactly one.

## Hashing

argon2-cffi with defaults (id, m=64 MiB, t=3, p=1). `audio_to_subs/auth/passwords.py` handles hash/verify.

## Sessions

itsdangerous.URLSafeTimedSerializer signing `{"user_id": int, "iat": int}` into `parolesub_session` cookie.

Flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when `BEHIND_TLS=true`.

TTL: 30 days with sliding renewal (renewed if >1 hour old on authenticated requests).

## Bootstrap and password reconcile

`audio_to_subs/auth/bootstrap.py` runs from the FastAPI lifespan on every startup:

1. Check `users` table
2. If empty and `ADMIN_USERNAME`/`ADMIN_PASSWORD` set → create user
3. If empty and no env vars → refuse to start
4. If non-empty and the resolved secret (`ADMIN_PASSWORD` / `ADMIN_PASSWORD_FILE`) differs from the stored hash → reconcile the hash to the new value
5. If non-empty and the secret is unset (`None`) → no-op (never lock the operator out as a side effect of an unrelated rotation)

This makes the deployment secret the single source of truth: rotating the Podman secret or `.env` `ADMIN_PASSWORD` and redeploying updates the stored credential automatically on the next boot — no CLI action required.

Placeholder/default passwords (`admin`, `changeme`, `password`, `root`, `123456`, empty) are refused on both the create and reconcile paths.

Admin CLI: `python -m audio_to_subs.admin db-init`, `whoami`. The `set-password` subcommand has been removed — the environment secret is the sole password mechanism.

## Security

- Password blocklist: `changeme`, `password`, `admin`, `root`, `123456`, empty string
- Placeholder refusal: bootstrap refuses default/placeholder passwords on create and on reconcile
- No rate limiting in v2 (can be added later with slowapi)
- No "forgot password" flow — rotate the deployment secret (`ADMIN_PASSWORD` / `ADMIN_PASSWORD_FILE`) and redeploy
- No CSRF tokens (SameSite=Lax + cookie auth sufficient for homelab)
- No OAuth/OIDC or MFA in v2

## Session Revocation

Not implemented. Upgrade path: add `session_secret` column to users table and bump on logout-all.