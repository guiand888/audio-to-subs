"""FastAPI dependencies for authentication."""

import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous.exc import BadSignature, SignatureExpired

from audio_to_subs.api.deps import SettingsDep
from audio_to_subs.auth.sessions import (
    SESSION_COOKIE_NAME,
    SLIDING_RENEWAL_THRESHOLD,
    get_session_manager,
)
from audio_to_subs.db.models import User
from audio_to_subs.db.session import get_async_session


async def get_db():
    """FastAPI dependency for async database session.

    Uses the configured DATABASE_URL (from settings) so tests and production
    both point at the right database without hardcoded path fallbacks.
    """
    from audio_to_subs.api.settings import get_settings

    async with get_async_session(get_settings().DATABASE_URL) as session:
        yield session


async def get_session_manager_dep() -> Any:
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


async def get_current_user(
    request: Request,
    response: Response,
    db: Annotated[Any, Depends(get_db)],
    session_manager: Annotated[Any, Depends(get_session_manager_dep)],
    settings: SettingsDep,
) -> User:
    """FastAPI dependency to get current authenticated user.
    
    Args:
        request: FastAPI request
        response: FastAPI response
        db: Async database session
        session_manager: Session manager instance
    
    Returns:
        User model instance
    
    Raises:
        HTTPException: 401 if not authenticated
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    
    try:
        payload = session_manager.validate_session(token)
    except SignatureExpired:
        # Clear the expired cookie
        response.delete_cookie(SESSION_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )
    except BadSignature:
        # Clear the invalid cookie
        response.delete_cookie(SESSION_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    
    user_id = payload.get("user_id")
    if user_id is None:
        response.delete_cookie(SESSION_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session payload",
        )
    
    # Fetch user from database
    from sqlalchemy import select
    from audio_to_subs.db.models import User
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if user is None:
        response.delete_cookie(SESSION_COOKIE_NAME)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    # Sliding renewal: renew session if older than threshold
    iat = payload.get("iat", 0)
    if (time.time() - iat) > SLIDING_RENEWAL_THRESHOLD:
        new_token = session_manager.renew_session(token)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=new_token,
            httponly=True,
            samesite="lax",
            path="/",
            secure=settings.BEHIND_TLS,  # Match login cookie security setting
            max_age=30 * 24 * 3600,  # 30 days
        )
    
    return user


async def get_optional_user(
    request: Request,
    db: Annotated[Any, Depends(get_db)],
    session_manager: Annotated[Any, Depends(get_session_manager_dep)],
) -> User | None:
    """FastAPI dependency to get current user if authenticated.
    
    Unlike get_current_user, this does not raise for unauthenticated requests.
    
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
    from audio_to_subs.db.models import User
    
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
