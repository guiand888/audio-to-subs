"""Shared helpers for route handlers.

Not a route module itself — no router defined here. Kept private (leading
underscore) since these are implementation details of the route layer, not
part of the public API surface.
"""

import logging
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable
from fastapi import HTTPException, status
from pydantic import BaseModel, model_validator
from sqlalchemy import select

from audio_to_subs.db.models import Job

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from audio_to_subs.api.settings import Settings

logger = logging.getLogger(__name__)


class UTCAwareModel(BaseModel):
    """Pydantic base that stamps naive datetime fields as UTC.

    The DB stores timestamps as naive UTC (SQLite ``CURRENT_TIMESTAMP``) and
    Pydantic v2 serializes naive datetimes WITHOUT an offset, which makes the
    wire format ambiguous: JavaScript's ``Date`` parser then treats the value
    as local time (the root cause of the "UI always shows UTC" symptom). This
    validator stamps any naive datetime field with ``timezone.utc`` after
    validation, so the serialized output carries an explicit ``+00:00``
    offset that the frontend can reliably convert to the user's timezone.

    Aware datetimes are left untouched (never double-stamped).
    """

    @model_validator(mode="after")
    def _stamp_utc_on_naive_datetimes(self) -> "UTCAwareModel":
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            if isinstance(value, datetime) and value.tzinfo is None:
                object.__setattr__(self, field_name, value.replace(tzinfo=timezone.utc))
        return self


async def get_job_or_404(db: "AsyncSession", job_id: str) -> Job:
    """Fetch a Job by id, or raise 404 if it doesn't exist.

    Job.id is a String(36) column; job_id is always converted to str for
    the comparison regardless of the caller's str type.
    """
    result = await db.execute(select(Job).where(Job.id == str(job_id)))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return job


async def publish_job_event(
    settings: "Settings",
    publish_fn: "Callable[[Redis, str], Awaitable[None]]",
    job_id: str,
    event_name: str,
) -> None:
    """Connect to Redis (if configured), publish a job event, then close.

    Best-effort: publish is fire-and-forget for the HTTP response — any
    failure (Redis unreachable, publish error) is logged and swallowed,
    never raised, so a Redis outage never breaks job creation/cancellation.
    The connection is always closed via try/finally, even if publish_fn
    raises.
    """
    try:
        if not settings.REDIS_URL:
            return
        import redis.asyncio as redis_lib

        redis = redis_lib.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]  # redis ships no stubs; from_url is untyped
        try:
            await publish_fn(redis, job_id)
        finally:
            await redis.close()
    except Exception as e:
        logger.error(f"Failed to publish {event_name}: {e}")
