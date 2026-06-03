"""FastAPI application factory."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from audio_to_subs.api.routes import auth, healthz
from audio_to_subs.api.routes.jobs import router as jobs_router
from audio_to_subs.api.routes.stream import router as stream_router
from audio_to_subs.api.routes.logs import (
    router as jobs_logs_router,
    global_logs_router,
)
from audio_to_subs.api.routes.settings import router as settings_router
from audio_to_subs.api.routes.wanted import router as wanted_router
from audio_to_subs.api.routes.history import router as history_router
from audio_to_subs.api.settings import get_settings
from audio_to_subs.auth.bootstrap import bootstrap_admin
from audio_to_subs.bazarr.poller import run_bazarr_poller, stop_poller
from audio_to_subs.db.session import init_db
from audio_to_subs.queue_.reaper import reap_stale_running

logger = logging.getLogger(__name__)

# Global reaper task
_reaper_task: asyncio.Task | None = None

# Global poller task
_poller_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Runs on startup and shutdown.
    """
    settings = get_settings()

    # Startup
    logger.info("Starting up...")

    # Initialize database
    logger.info("Initializing database...")
    await init_db(settings.DATABASE_URL)

    # Run migrations
    logger.info("Running database migrations...")
    import subprocess

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    if result.returncode != 0:
        logger.error("Failed to run migrations: %s", result.stderr)
        raise RuntimeError(f"Migration failed: {result.stderr}")
    logger.info("Database migrations applied")

    # Bootstrap admin user
    logger.info("Bootstrapping admin user...")
    from audio_to_subs.db.session import get_async_session

    async with get_async_session(settings.DATABASE_URL) as session:
        try:
            await bootstrap_admin(
                session,
                username=settings.ADMIN_USERNAME,
                password=settings.admin_password,
            )
        except ValueError as e:
            logger.error("Admin bootstrap failed: %s", str(e))
            raise RuntimeError(str(e)) from e

    # Start reaper task
    global _reaper_task
    _reaper_task = asyncio.create_task(
        _run_reaper_periodically(settings.DATABASE_URL)
    )
    logger.info("Reaper task started")

    # Start Bazarr poller task
    global _poller_task
    _poller_task = asyncio.create_task(run_bazarr_poller(app))
    logger.info("Bazarr poller task started")

    logger.info("Startup complete")

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Cancel Bazarr poller task
    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass

    # Cancel reaper task
    if _reaper_task:
        _reaper_task.cancel()
        try:
            await _reaper_task
        except asyncio.CancelledError:
            pass

    logger.info("Shutdown complete")


async def _run_reaper_periodically(database_url: str) -> None:
    """Run the reaper periodically to clean up stale jobs."""
    while True:
        try:
            from audio_to_subs.db.session import get_async_session

            async with get_async_session(database_url) as session:
                reaped = reap_stale_running(session, stale_seconds=120)
                if reaped > 0:
                    logger.info(f"Reaper: {reaped} stale jobs requeued")
        except Exception as e:
            logger.error(f"Reaper error: {e}")

        await asyncio.sleep(60)  # Run every 60 seconds


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        FastAPI application instance
    """
    settings = get_settings()

    app = FastAPI(
        title="audio-to-subs v2 API",
        description="API for audio-to-subs v2 transcription service",
        version="2.0.0",
        lifespan=lifespan,
        debug=settings.DEBUG,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Will be restricted in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(healthz.router)
    app.include_router(auth.router)
    app.include_router(settings_router)
    app.include_router(wanted_router)
    app.include_router(jobs_router)
    app.include_router(stream_router)
    app.include_router(jobs_logs_router)
    app.include_router(global_logs_router)
    app.include_router(history_router)

    return app


# Global app instance
_app: FastAPI | None = None


def get_app() -> FastAPI:
    """Get or create application instance.

    Returns:
        FastAPI application instance
    """
    global _app
    if _app is None:
        _app = create_app()
    return _app


# For running with uvicorn: uvicorn audio_to_subs.api.app:app
app = create_app()
