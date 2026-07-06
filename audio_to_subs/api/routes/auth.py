"""Authentication routes."""

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from audio_to_subs.api.deps import SettingsDep
from audio_to_subs.auth.deps import get_current_user, get_db
from audio_to_subs.auth.passwords import verify_password
from audio_to_subs.auth.sessions import SESSION_COOKIE_NAME, get_session_manager
from audio_to_subs.db.models import User

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

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Verify password
    if not verify_password(login_request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Update last login time
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    # Create session
    session_manager = get_session_manager(
        secret=settings.SESSION_SECRET,
        secret_file=settings.SESSION_SECRET_FILE,
    )
    token = session_manager.create_session(user.id)

    # Set cookie
    secure = settings.BEHIND_TLS
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
        max_age=30 * 24 * 3600,  # 30 days
    )

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
