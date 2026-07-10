"""FastAPI dependencies for authentication."""

import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous.exc import BadSignature, SignatureExpired
from sqlalchemy.ext.asyncio import AsyncSession

from audio_to_subs.auth.sessions import (
    SESSION_COOKIE_NAME,
    SLIDING_RENEWAL_THRESHOLD,
    SessionManager,
    get_session_manager,
    set_session_cookie,
)
from audio_to_subs.db.models import User
from audio_to_subs.db.session import get_async_session

if TYPE_CHECKING:
    from audio_to_subs.api.settings import Settings


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database session.

    Uses the configured DATABASE_URL (from settings) so tests and production
    both point at the right database without hardcoded path fallbacks.
    """
    from audio_to_subs.api.settings import get_settings

    async with get_async_session(get_settings().DATABASE_URL) as session:
        yield session


async def get_session_manager_dep() -> SessionManager:
    """FastAPI dependency for session manager.

    Reads SESSION_SECRET / SESSION_SECRET_FILE from settings so the manager
    is always initialised with the right secret, including in tests where
    the env var is set but the secret file does not exist.
    """
    from audio_to_subs.api.settings import get_settings

    settings = get_settings()
    return get_session_manager(
        secret=settings.SESSION_SECRET,
        secret_file=settings.SESSION_SECRET_FILE,
    )


async def get_settings_dep() -> "Settings":
    """FastAPI dependency for settings (local version to avoid circular import)."""
    from audio_to_subs.api.settings import get_settings

    return get_settings()


SettingsDep = Annotated["Settings", Depends(get_settings_dep)]


async def _resolve_user(
    token: str | None,
    response: Response,
    db: AsyncSession,
    session_manager: SessionManager,
) -> tuple[User, dict[str, Any]]:
    """Resolve and validate user from session token.

    Extracts user_id from session token, validates the session,
    and fetches the user from the database. On validation failure,
    deletes the session cookie and raises HTTPException.

    Args:
        token: Session token from cookie (may be None)
        response: FastAPI response (for deleting cookies)
        db: Database session
        session_manager: Session manager instance

    Returns:
        Tuple of (user, payload) where payload is the decoded session data

    Raises:
        HTTPException: 401 if not authenticated or validation fails
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = session_manager.validate_session(token)
    except SignatureExpired as err:
        response.delete_cookie(SESSION_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        ) from err
    except BadSignature as err:
        response.delete_cookie(SESSION_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        ) from err

    user_id = payload.get("user_id")
    if user_id is None:
        response.delete_cookie(SESSION_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session payload",
        )

    # Fetch user from database
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        response.delete_cookie(SESSION_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user, payload


async def get_current_user(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    session_manager: Annotated[SessionManager, Depends(get_session_manager_dep)],
    settings: SettingsDep,
) -> User:
    """FastAPI dependency to get current authenticated user.

    Validates the session token, fetches the user from the database,
    and handles sliding session renewal.

    Args:
        request: FastAPI request
        response: FastAPI response
        db: Async database session
        session_manager: Session manager instance
        settings: Application settings

    Returns:
        User model instance

    Raises:
        HTTPException: 401 if not authenticated
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user, payload = await _resolve_user(token, response, db, session_manager)

    # Sliding renewal: renew session if older than threshold
    iat = payload.get("iat", 0)
    if (time.time() - iat) > SLIDING_RENEWAL_THRESHOLD:
        # token is guaranteed non-None here: _resolve_user() above already
        # raised 401 if it were None.
        assert token is not None
        new_token = session_manager.renew_session(token)
        set_session_cookie(response, new_token, secure=settings.BEHIND_TLS)

    return user


async def get_optional_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    session_manager: Annotated[SessionManager, Depends(get_session_manager_dep)],
) -> User | None:
    """FastAPI dependency to get current user if authenticated.

    Unlike get_current_user, this does not raise for unauthenticated requests
    and does not delete cookies on validation failure.

    Args:
        request: FastAPI request
        db: Async database session
        session_manager: Session manager instance

    Returns:
        User model instance or None if not authenticated
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)

    if token is None:
        return None

    try:
        payload = session_manager.validate_session(token)
    except (SignatureExpired, BadSignature):
        return None

    user_id = payload.get("user_id")
    if user_id is None:
        return None

    from sqlalchemy import select

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
