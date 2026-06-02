"""Database session factories.

Async and sync session factories for SQLAlchemy 2.x.
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from audio_to_subs.db.base import Base, get_async_engine, get_sync_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import create_async_engine


# Default DSN
DEFAULT_ASYNC_DSN = "sqlite+aiosqlite:////data/audio-to-subs.db"
DEFAULT_SYNC_DSN = "sqlite:////data/audio-to_subs.db"


@asynccontextmanager
async def get_async_session(
    dsn: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database session.
    
    Args:
        dsn: Database URL. If None, uses default.
    
    Yields:
        Async SQLAlchemy session
    """
    if dsn is None:
        dsn = DEFAULT_ASYNC_DSN
    engine = get_async_engine(dsn)
    
    async with engine.begin() as conn:
        # Ensure all models are registered
        await conn.run_sync(Base.metadata.create_all)
    
    async with engine.connect() as conn:
        # Enable foreign keys for SQLite
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.commit()
    
    async with engine.begin() as conn:
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@contextmanager
def get_sync_session(
    dsn: str | None = None,
) -> Generator[Session, None, None]:
    """Sync context manager for database session.
    
    Args:
        dsn: Database URL. If None, uses default.
    
    Yields:
        Sync SQLAlchemy session
    """
    if dsn is None:
        dsn = DEFAULT_SYNC_DSN
    engine = get_sync_engine(dsn)
    
    with engine.connect() as conn:
        # Ensure all models are registered
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def init_db(dsn: str | None = None) -> None:
    """Initialize database with all tables.
    
    Args:
        dsn: Database URL. If None, uses default.
    """
    if dsn is None:
        dsn = DEFAULT_ASYNC_DSN
    engine = get_async_engine(dsn)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.commit()
