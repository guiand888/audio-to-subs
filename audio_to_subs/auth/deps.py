"""FastAPI dependencies for authentication."""

import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous.exc import BadSignature, SignatureExpired

from audio_to_subs.auth.sessions import (
    SESSION_COOKIE_NAME,
    SLIDING_RENEWAL_THRESHOLD,
    get_session_manager,
)
from audio_to_subs.db.models import User
from audio_to_subs.db.session import get_async_session


async def get_db():
    """FastAPI dependency for async database session."""
    async for session in get_async_session():
        yield session


async def get_session_manager_dep(
    session_secret: Annotated[str | None, Depends(lambda: None)],
    session_secret_file: Annotated[str | None, Depends(lambda: None)],
) -> Any:
    """FastAPI dependency for session manager."""
    # These would come from settings in a real implementation
    return get_session_manager()


async def get_current_user(
    request: Request,
    response: Response,
    db: Annotated[Any, Depends(get_db)],
    session_manager: Annotated[Any, Depends(get_session_manager_dep)],
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
            secure=False,  # Will be configurable via BEHIND_TLS
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
