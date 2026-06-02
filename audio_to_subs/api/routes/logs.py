"""Log routes for job logging."""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.orm import joinedload

from audio_to_subs.api.deps import get_db
from audio_to_subs.db.models import Job, JobLog, LogLevel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/jobs", tags=["logs"])


class JobLogResponse(BaseModel):
    """Response model for a job log entry."""

    id: int
    job_id: UUID
    ts: datetime
    level: LogLevel
    message: str

    class Config:
        from_attributes = True


class JobLogsResponse(BaseModel):
    """Response model for job logs list."""

    logs: list[JobLogResponse]
    total: int


@router.get("/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(
    job_id: UUID,
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    limit: int = 100,
    offset: int = 0,
    level_filter: LogLevel | None = None,
) -> JobLogsResponse:
    """Get logs for a specific job.

    Returns a paginated list of log entries for the job, ordered by timestamp.
    """
    # Verify job exists
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Build query
    query = select(JobLog).where(JobLog.job_id == job_id)

    # Apply level filter if provided
    if level_filter is not None:
        query = query.where(JobLog.level == level_filter)

    # Get total count
    count_result = await db.execute(
        select(func.count(JobLog.id)).where(JobLog.job_id == job_id)
    )
    total = count_result.scalar()

    # Get paginated logs
    query = query.order_by(desc(JobLog.ts)).limit(limit).offset(offset)
    result = await db.execute(query)
    logs = result.scalars().all()

    return JobLogsResponse(
        logs=[JobLogResponse.model_validate(log) for log in logs],
        total=total,
    )


@router.post(
    "/{job_id}/logs",
    response_model=JobLogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_job_log(
    job_id: UUID,
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    level: LogLevel = LogLevel.INFO,
    message: str = ...,
) -> JobLogResponse:
    """Create a log entry for a job.

    Used internally by the API and worker to record job lifecycle events.
    """
    # Verify job exists
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Create log entry
    log_entry = JobLog(
        job_id=job_id,
        ts=datetime.utcnow(),
        level=level,
        message=message,
    )

    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)

    return JobLogResponse.model_validate(log_entry)
