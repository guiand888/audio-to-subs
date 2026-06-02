"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from audio_to_subs.api.routes import auth, healthz
from audio_to_subs.api.settings import get_settings
from audio_to_subs.auth.bootstrap import bootstrap_admin
from audio_to_subs.db.session import init_db

logger = logging.getLogger(__name__)


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
    
    logger.info("Startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    logger.info("Shutdown complete")


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
