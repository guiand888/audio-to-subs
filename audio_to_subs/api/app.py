"""FastAPI application factory."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any

from fastapi import Depends, FastAPI
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
from audio_to_subs.bazarr.poller import start_poller, stop_poller
from audio_to_subs.queue_.reaper import reap_stale_running

logger = logging.getLogger(__name__)

# Global reaper task
_reaper_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Runs on startup and shutdown.
    """
    import asyncio
    import subprocess

    settings = get_settings()

    # Startup
    logger.info("Starting up...")

    # Run migrations (Alembic is the single source of truth for the schema)
    # Run in thread pool to avoid blocking the event loop
    logger.info("Running database migrations...")
    result = await asyncio.to_thread(
        subprocess.run,
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    if result.returncode != 0:
        logger.error("Failed to run migrations: %s", result.stderr)
        raise RuntimeError(f"Migration failed: {result.stderr}")
    logger.info("Database migrations applied")

    # Bootstrap session secret: generate and persist one if not provided via
    # SESSION_SECRET and no secret file exists yet. Persisted to the data
    # volume so sessions survive restarts.
    if not settings.SESSION_SECRET and settings.SESSION_SECRET_FILE:
        from pathlib import Path

        from audio_to_subs.auth.sessions import SessionManager

        if not Path(settings.SESSION_SECRET_FILE).exists():
            SessionManager.write_secret_file(settings.SESSION_SECRET_FILE)
            logger.info(
                "Generated new session secret at %s", settings.SESSION_SECRET_FILE
            )

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

    # Create the shutdown event that run_bazarr_poller watches, then start the
    # poller via the canonical helper that manages app.state.poller_task.
    app.state.shutdown = asyncio.Event()
    await start_poller(app)
    logger.info("Bazarr poller task started")

    logger.info("Startup complete")

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Signal and await the Bazarr poller via the matching helper.
    app.state.shutdown.set()
    await stop_poller(app)

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
                reaped = await reap_stale_running(session, stale_seconds=120)
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

    # Include routers.
    # stream_router MUST come before jobs_router: /api/jobs/stream is a literal
    # path that would otherwise be shadowed by jobs_router's /{job_id} pattern.

    # Healthz and auth endpoints stay open (no authentication required)
    app.include_router(healthz.router)
    app.include_router(auth.router)

    # All other routers require authentication
    from audio_to_subs.auth.deps import get_current_user
    auth_dependency = Depends(get_current_user)

    app.include_router(settings_router, dependencies=[auth_dependency])
    app.include_router(wanted_router, dependencies=[auth_dependency])
    app.include_router(stream_router, dependencies=[auth_dependency])
    app.include_router(jobs_logs_router, dependencies=[auth_dependency])
    app.include_router(jobs_router, dependencies=[auth_dependency])
    app.include_router(global_logs_router, dependencies=[auth_dependency])
    app.include_router(history_router, dependencies=[auth_dependency])

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
