"""Shared helpers for route handlers.

Not a route module itself — no router defined here. Kept private (leading
underscore) since these are implementation details of the route layer, not
part of the public API surface.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select

from audio_to_subs.db.models import Job

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_job_or_404(db: "AsyncSession", job_id: UUID) -> Job:
    """Fetch a Job by id, or raise 404 if it doesn't exist.

    Job.id is a String(36) column; job_id is always converted to str for
    the comparison regardless of the caller's UUID/str type.
    """
    result = await db.execute(select(Job).where(Job.id == str(job_id)))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return job
