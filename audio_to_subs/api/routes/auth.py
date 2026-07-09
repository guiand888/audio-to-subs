"""Authentication routes."""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from audio_to_subs.api.deps import SettingsDep
from audio_to_subs.auth.deps import get_current_user, get_db, get_session_manager_dep
from audio_to_subs.auth.passwords import hash_password, verify_password
from audio_to_subs.auth.sessions import (
    SESSION_COOKIE_NAME,
    SessionManager,
    set_session_cookie,
)
from audio_to_subs.db.job_logs import write_job_log
from audio_to_subs.db.models import LogLevel, User

logger = logging.getLogger(__name__)

# Precomputed hash for a password that will never match, used to keep the
# login endpoint's timing constant when the username doesn't exist — otherwise
# an unknown username short-circuits before the argon2id verify and its
# response time leaks which usernames are registered.
_DUMMY_PASSWORD_HASH = hash_password(SessionManager.generate_secret())

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request body."""

    username: str
    password: str


class UserOut(BaseModel):
    """User response model."""

    id: int
    username: str


class LoginResponse(BaseModel):
    """Login response model."""

    user: UserOut


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    response: Response,
    login_request: LoginRequest,
    db: Annotated[Any, Depends(get_db)],
    settings: SettingsDep,
    session_manager: Annotated[SessionManager, Depends(get_session_manager_dep)],
) -> LoginResponse:
    """Login endpoint.

    Authenticates user and sets session cookie.
    No authentication required.
    """
    from sqlalchemy import select

    # Find user by username
    result = await db.execute(
        select(User).where(User.username == login_request.username)
    )
    user = result.scalar_one_or_none()

    # Always verify against a hash, even for an unknown username, so the
    # response time doesn't reveal whether the username exists.
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(login_request.password, password_hash)

    if user is None or not password_ok:
        logger.warning("Failed login attempt for username %r", login_request.username)
        await write_job_log(
            db,
            LogLevel.WARNING,
            f"Failed login attempt for username '{login_request.username}'",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Update last login time
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    # Create session
    token = session_manager.create_session(user.id)
    set_session_cookie(response, token, secure=settings.BEHIND_TLS)

    logger.info("User '%s' logged in", user.username)
    await write_job_log(db, LogLevel.INFO, f"User '{user.username}' logged in")

    return LoginResponse(user=UserOut(id=user.id, username=user.username))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
) -> None:
    """Logout endpoint.

    Clears session cookie.
    Authentication required.
    """
    response.delete_cookie(SESSION_COOKIE_NAME)


@router.get("/me", response_model=UserOut)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> UserOut:
    """Get current user.

    Returns the authenticated user.
    Authentication required.
    """
    return UserOut(id=user.id, username=user.username)
