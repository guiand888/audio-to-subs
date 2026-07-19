# Authentication

Single admin user. Multi-user-ready schema (`users` table can hold N rows), but bootstrap creates exactly one.

## Hashing

argon2-cffi with defaults (id, m=64 MiB, t=3, p=1). `audio_to_subs/auth/passwords.py` handles hash/verify.

## Sessions

itsdangerous.URLSafeTimedSerializer signing `{"user_id": int, "iat": int}` into `parolesub_session` cookie.

Flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when `BEHIND_TLS=true`.

TTL: 30 days with sliding renewal (renewed if >1 hour old on authenticated requests).

## Bootstrap

`audio_to_subs/auth/bootstrap.py` run from FastAPI lifespan and worker boot:
1. Check `users` table
2. If empty and `ADMIN_USERNAME`/`ADMIN_PASSWORD` set → create user
3. If empty and no env vars → refuse to start
4. If non-empty → env vars ignored

Admin CLI: `python -m audio_to_subs.admin set-password`, `db-init`, `whoami`.

## Security

- Password blocklist: `changeme`, `password`, `admin`, `root`, `123456`, empty string
- Placeholder refusal: Bootstraps refuses default/placeholder passwords
- No rate limiting in v2 (can be added later with slowapi)
- No "forgot password" flow (use admin CLI)
- No CSRF tokens (SameSite=Lax + cookie auth sufficient for homelab)
- No OAuth/OIDC or MFA in v2

## Session Revocation

Not implemented. Upgrade path: add `session_secret` column to users table and bump on logout-all.