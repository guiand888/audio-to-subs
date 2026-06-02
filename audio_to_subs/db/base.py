"""Database engine and WAL pragmas configuration.

SQLite with WAL mode for concurrent read/write access.
SQLAlchemy 2.x ORM.
"""

from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# WAL pragmas to apply on every new connection
WAL_PRAGMAS = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "busy_timeout": 5000,  # 5 seconds
    "foreign_keys": "ON",
}


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class."""

    pass


# Async engine for FastAPI
_async_engine: create_async_engine | None = None


def get_async_engine(dsn: str) -> create_async_engine:
    """Create and return async SQLAlchemy engine with WAL pragmas.
    
    Args:
        dsn: Database URL, e.g., 'sqlite+aiosqlite:////data/audio-to-subs.db'
    
    Returns:
        SQLAlchemy async engine with WAL pragmas configured
    """
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(dsn, echo=False)
        _configure_wal_pragmas_async(_async_engine)
    return _async_engine


def _configure_wal_pragmas_async(engine: create_async_engine) -> None:
    """Configure WAL pragmas on async engine connections."""

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(connection):
        for key, value in WAL_PRAGMAS.items():
            connection.execute(f"PRAGMA {key} = {value}")


# Sync engine for worker
_sync_engine: None = None


def get_sync_engine(dsn: str):
    """Create and return sync SQLAlchemy engine with WAL pragmas.
    
    Args:
        dsn: Database URL, e.g., 'sqlite:////data/audio-to-subs.db'
    
    Returns:
        SQLAlchemy sync engine with WAL pragmas configured
    """
    from sqlalchemy import create_engine

    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(dsn.replace("sqlite+aiosqlite", "sqlite"), echo=False)
        _configure_wal_pragmas_sync(_sync_engine)
    return _sync_engine


def _configure_wal_pragmas_sync(engine):
    """Configure WAL pragmas on sync engine connections."""

    @event.listens_for(engine, "connect")
    def _on_connect(connection):
        for key, value in WAL_PRAGMAS.items():
            connection.execute(f"PRAGMA {key} = {value}")


# Async session factory
_async_sessionmaker: async_sessionmaker | None = None


def get_async_sessionmaker(engine: create_async_engine) -> async_sessionmaker:
    """Create and return async session factory.
    
    Args:
        engine: Async SQLAlchemy engine
    
    Returns:
        Async session maker factory
    """
    global _async_sessionmaker
    if _async_sessionmaker is None:
        _async_sessionmaker = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
    return _async_sessionmaker


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database session."""
    engine = get_async_engine("sqlite+aiosqlite:////data/audio-to-subs.db")
    sessionmaker = get_async_sessionmaker(engine)
    async with sessionmaker() as session:
        yield session


# Sync session factory
_sync_sessionmaker = None


def get_sync_sessionmaker(engine):
    """Create and return sync session factory.
    
    Args:
        engine: Sync SQLAlchemy engine
    
    Returns:
        Sync session maker factory
    """
    from sqlalchemy.orm import Session

    global _sync_sessionmaker
    if _sync_sessionmaker is None:
        _sync_sessionmaker = sessionmaker(
            engine, expire_on_commit=False, class_=Session
        )
    return _sync_sessionmaker
