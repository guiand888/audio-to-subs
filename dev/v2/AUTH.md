# v2 — Authentication

Single admin user. Multi-user-ready schema (`users` table can hold N rows), but the bootstrap creates exactly one and the UI has no "create user" page in v2.

## Hashing

- **argon2-cffi**, defaults (id, m=64 MiB, t=3, p=1). Defaults are safe for this workload.
- `audio_to_subs/auth/passwords.py`:

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_PH = PasswordHasher()

def hash_password(plain: str) -> str:
    return _PH.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _PH.verify(hashed, plain)
    except VerifyMismatchError:
        return False
```

## Sessions

- **`itsdangerous.URLSafeTimedSerializer(SESSION_SECRET)`** signing `{"user_id": int, "iat": int}` into a single cookie.
- Cookie name: `ats_session`.
- Cookie flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when `BEHIND_TLS=true` (env-controlled — the homelab default is `false`).
- TTL: 30 days with sliding renewal: on every authenticated request, if the cookie is older than 1 hour, re-sign with the same `user_id` and a fresh `iat`.
- `SESSION_SECRET` from env (or `SESSION_SECRET_FILE` → secret file). On first boot, if no secret is set, generate one and write it to `/data/session_secret` (chmod 600). Refuse to start with a default placeholder.

### Why no `sessions` table

Signed cookies are stateless: no DB round-trip per request, no cleanup job, no replication concerns. The only thing a DB table would buy is server-side revocation; we don't have a use case for that in v2. If we ever need it, a 10-line migration adds a `session_secret` column to `users` that we bump on logout-all. Documented as the upgrade path; not implemented.

## FastAPI dependencies

`audio_to_subs/auth/deps.py`:

```python
from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired

async def get_current_user(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> User:
    token = request.cookies.get("ats_session")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    try:
        payload = serializer.loads(token, max_age=30 * 24 * 3600)
    except SignatureExpired:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    except BadSignature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    user = await db.get(User, payload["user_id"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    # sliding renewal
    if time.time() - payload["iat"] > 3600:
        _set_session_cookie(response, user.id, serializer)
    return user
```

Every protected route declares `user: User = Depends(get_current_user)`.

## Bootstrap flow

`audio_to_subs/auth/bootstrap.py`, run from the FastAPI lifespan and from the worker boot:

1. Check the `users` table.
2. If empty:
   - If `ADMIN_USERNAME` and `ADMIN_PASSWORD` (or `ADMIN_PASSWORD_FILE`) env vars are set → create the user, log `info`: `"bootstrapped admin '%s' from env"`.
   - Else → log `error`: `"no users exist and ADMIN_USERNAME/ADMIN_PASSWORD not set; run 'python -m audio_to_subs.admin set-password'"` and **refuse to start** (FastAPI lifespan raises, container exits non-zero).
3. If non-empty: env vars are **ignored**. Never silently reset an existing password.

The admin CLI (`audio_to_subs/admin/__main__.py`) implements:

```
python -m audio_to_subs.admin set-password [--username admin]
python -m audio_to_subs.admin db-init        # alembic upgrade head, idempotent
python -m audio_to_subs.admin whoami         # diagnostic: lists users
```

`set-password` prompts (via `getpass`) for username (default: only existing user, or "admin") and password (twice).

## Login route

`POST /api/auth/login`:

```python
class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
async def login(req: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.username == req.username))
    if user is None or not verify_password(req.password, user.password_hash):
        # constant-time-ish: do a dummy hash to avoid timing oracle
        verify_password(req.password, _DUMMY_HASH)
        raise HTTPException(401, "Invalid credentials")
    _set_session_cookie(response, user.id, get_serializer())
    user.last_login_at = func.now()
    await db.commit()
    return {"user": {"id": user.id, "username": user.username}}
```

`_DUMMY_HASH` is a pre-computed argon2 hash of a random string, kept as a module constant. It makes login latency for "user does not exist" similar to "wrong password".

## Logout

`POST /api/auth/logout`: clears the cookie with `Set-Cookie: ats_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax`. Returns 204.

## Rate limiting

Not in v2.0. If brute-force becomes a worry, add `slowapi` later with a per-IP limit on `/api/auth/login`. Document as a known gap.

## Tests

- `tests/test_auth_passwords.py` — round-trip hash/verify; verify returns `False` (not raises) on mismatch; rejects empty password.
- `tests/test_auth_sessions.py` — serialiser round-trip; tampered cookie rejected; expired cookie rejected (`SignatureExpired`).
- `tests/test_auth_bootstrap.py` — empty DB + env set → user created; empty DB + env unset → lifespan raises; non-empty DB → env ignored.
- `tests/test_api_auth.py` — `TestClient` flow: login → cookie set → `/api/auth/me` works → logout → cookie cleared → `/api/auth/me` 401.
- `tests/test_api_auth_timing.py` (optional) — login latency for valid vs. invalid username should be within tolerance (cheap sanity, not a real timing-attack test).

## What v2 explicitly does NOT do

- No "forgot password" flow. Operator uses `python -m audio_to_subs.admin set-password`.
- No CSRF tokens. `SameSite=Lax` + cookie-based auth + no third-party origins means CSRF surface is minimal for a homelab tool. If embedded into a multi-tenant deployment later, add CSRF tokens.
- No OAuth/OIDC. Skip even if the operator runs Authelia/Authentik; that's a v3 conversation.
- No MFA.
