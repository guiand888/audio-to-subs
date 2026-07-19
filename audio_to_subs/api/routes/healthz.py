"""Health check endpoint."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from audio_to_subs.api.deps import SettingsDep
from audio_to_subs.db.session import get_async_session

router = APIRouter(prefix="/api", tags=["healthz"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: str
    redis: str | None = None


@router.get("/healthz", response_model=HealthResponse)
async def healthz(
    settings: SettingsDep,
) -> HealthResponse:
    """Health check endpoint.

    Returns 200 if all services are healthy.
    No authentication required.
    """
    # Check database
    try:
        async with get_async_session(settings.DATABASE_URL) as session:
            # Simple query to verify connection
            await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Check Redis
    redis_status: str | None = None
    try:
        import redis.asyncio as redis

        redis_client = redis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]  # redis ships no stubs; from_url is untyped
        await redis_client.ping()
        await redis_client.close()
        redis_status = "ok"
    except ImportError:
        # Redis library not installed
        redis_status = "skipped: redis library not installed"
    except Exception as e:
        redis_status = f"error: {str(e)}"

    # Determine overall status
    if db_status != "ok":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"database": db_status, "redis": redis_status},
        )

    return HealthResponse(
        status="ok",
        database=db_status,
        redis=redis_status,
    )
