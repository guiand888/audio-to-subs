"""Database engine and WAL pragmas configuration.

SQLite with WAL mode for concurrent read/write access.
SQLAlchemy 2.x ORM.
"""

from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
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


# Async engine cache - keyed by DSN to support multiple databases
_async_engines: dict[str, AsyncEngine] = {}


def get_async_engine(dsn: str) -> AsyncEngine:
    """Create and return async SQLAlchemy engine with WAL pragmas.

    Caches engines per DSN to support multiple databases (e.g., admin CLI
    connecting to different DB than the main app).

    Args:
        dsn: Database URL, e.g., 'sqlite+aiosqlite:////data/audio-to-subs.db'

    Returns:
        SQLAlchemy async engine with WAL pragmas configured
    """
    global _async_engines
    if dsn not in _async_engines:
        _async_engines[dsn] = create_async_engine(dsn, echo=False)
        _install_sqlite_listeners(_async_engines[dsn].sync_engine)
    return _async_engines[dsn]


def _install_sqlite_listeners(sync_engine: Engine) -> None:
    """Install WAL/BEGIN-IMMEDIATE pragma listeners on a sync engine.

    SQLAlchemy always dispatches DBAPI-level connection events against the
    underlying sync ``Engine`` object — for the async engine that means its
    ``.sync_engine`` — so this single helper covers both the async engine
    (worker/API) and the plain sync engine (used elsewhere) with identical
    listener logic.
    """

    @event.listens_for(sync_engine, "connect")
    def _on_connect(dbapi_connection, connection_record):
        # Disable pysqlite's implicit transaction management so we can emit our
        # own BEGIN IMMEDIATE below. Without this, transactions start DEFERRED:
        # a SELECT-then-UPDATE acquires a read lock first, then fails instantly
        # with SQLITE_BUSY on the read->write upgrade (busy_timeout does not
        # apply to lock upgrades). See sqlite "database is locked" gotcha.
        dbapi_connection.isolation_level = None
        for key, value in WAL_PRAGMAS.items():
            dbapi_connection.execute(f"PRAGMA {key} = {value}")

    @event.listens_for(sync_engine, "begin")
    def _on_begin(conn):
        # Acquire the write lock up front; busy_timeout then makes concurrent
        # writers wait politely instead of erroring.
        conn.exec_driver_sql("BEGIN IMMEDIATE")


# Sync engine for worker
_sync_engine: Engine | None = None


def get_sync_engine(dsn: str) -> Engine:
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
        _install_sqlite_listeners(_sync_engine)
    return _sync_engine


# Async session factory
_async_sessionmakers: dict[int, async_sessionmaker] = {}


def get_async_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    """Create and return async session factory.

    Caches sessionmakers per engine instance to support multiple databases.

    Args:
        engine: Async SQLAlchemy engine

    Returns:
        Async session maker factory
    """
    global _async_sessionmakers
    engine_id = id(engine)
    if engine_id not in _async_sessionmakers:
        _async_sessionmakers[engine_id] = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
    return _async_sessionmakers[engine_id]


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database session."""
    engine = get_async_engine("sqlite+aiosqlite:////data/audio-to-subs.db")
    sessionmaker = get_async_sessionmaker(engine)
    async with sessionmaker() as session:
        yield session


# Sync session factory cache - keyed by engine instance
_sync_sessionmakers: dict[int, sessionmaker] = {}


def get_sync_sessionmaker(engine):
    """Create and return sync session factory.

    Caches sessionmakers per engine instance to support multiple databases.

    Args:
        engine: Sync SQLAlchemy engine

    Returns:
        Sync session maker factory
    """
    from sqlalchemy.orm import Session

    global _sync_sessionmakers
    engine_id = id(engine)
    if engine_id not in _sync_sessionmakers:
        _sync_sessionmakers[engine_id] = sessionmaker(
            engine, expire_on_commit=False, class_=Session
        )
    return _sync_sessionmakers[engine_id]
