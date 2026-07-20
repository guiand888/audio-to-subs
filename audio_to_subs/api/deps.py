"""FastAPI dependencies for the API."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from audio_to_subs.api.settings import Settings, get_settings
from audio_to_subs.auth.deps import get_current_user, get_db, get_optional_user
from audio_to_subs.db.models import User

__all__ = [
    "get_settings_dep",
    "get_redis",
    "get_redis_client",
    "CurrentUser",
    "OptionalUser",
    "DatabaseSession",
    "SettingsDep",
    "get_db",
]


def get_settings_dep() -> Settings:
    """FastAPI dependency for settings."""
    return get_settings()


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency for Redis client.

    Creates a Redis connection from settings.REDIS_URL.
    """
    import redis.asyncio as redis_lib

    settings = get_settings()
    redis = redis_lib.from_url(settings.REDIS_URL)
    try:
        yield redis
    finally:
        await redis.close()


def get_redis_client() -> Redis:
    """Create a standalone Redis client (for use outside a request scope).

    Callers are responsible for closing it via ``redis.aclose()``.
    """
    import redis.asyncio as redis_lib

    settings = get_settings()
    return redis_lib.from_url(settings.REDIS_URL)  # type: ignore[no-any-return]


# Re-export from auth.deps for convenience
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
