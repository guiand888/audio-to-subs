"""Database session factories.

Async and sync session factories for SQLAlchemy 2.x.
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from audio_to_subs.db.base import Base, get_async_engine, get_sync_engine

# Default DSN
DEFAULT_ASYNC_DSN = "sqlite+aiosqlite:////data/audio-to-subs.db"
DEFAULT_SYNC_DSN = "sqlite:////data/audio-to-subs.db"


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

    # NOTE: schema is owned by Alembic migrations (run at startup); do NOT call
    # create_all here, and do NOT wrap the session in an outer engine.begin() —
    # that holds a separate write transaction open for the session's lifetime
    # and deadlocks every write with "database is locked".
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
