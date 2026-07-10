"""Log routes for job logging and global logs."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select

from audio_to_subs.api.deps import get_db
from audio_to_subs.api.routes._helpers import UTCAwareModel, get_job_or_404
from audio_to_subs.db.models import JobLog, LogLevel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Router for job-specific logs (/api/jobs/{id}/logs)
jobs_logs_router = APIRouter(prefix="/api/jobs", tags=["logs"])

# Router for global logs (/api/logs)
global_logs_router = APIRouter(prefix="/api/logs", tags=["logs"])


class JobLogResponse(UTCAwareModel):
    """Response model for a job log entry."""

    model_config = {"from_attributes": True}

    id: int
    job_id: UUID | None  # nullable — global logs have no associated job
    ts: datetime
    level: LogLevel
    message: str


class JobLogsResponse(BaseModel):
    """Response model for job logs list."""

    logs: list[JobLogResponse]
    total: int


@jobs_logs_router.get("/{job_id}/logs", response_model=JobLogsResponse)
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
    await get_job_or_404(db, job_id)

    # Build query
    query = select(JobLog).where(JobLog.job_id == str(job_id))

    # Apply level filter if provided
    if level_filter is not None:
        query = query.where(JobLog.level == level_filter)

    # Get total count (respecting filters)
    count_query = select(func.count(JobLog.id)).where(JobLog.job_id == str(job_id))
    if level_filter is not None:
        count_query = count_query.where(JobLog.level == level_filter)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Get paginated logs
    query = query.order_by(desc(JobLog.ts)).limit(limit).offset(offset)
    result = await db.execute(query)
    logs = result.scalars().all()

    return JobLogsResponse(
        logs=[JobLogResponse.model_validate(log) for log in logs],
        total=total,
    )


@jobs_logs_router.post(
    "/{job_id}/logs",
    response_model=JobLogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_job_log(
    job_id: UUID,
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    level: LogLevel = LogLevel.INFO,
    # Ellipsis is FastAPI's convention for "required" on a param that must
    # follow ones with real defaults; mypy doesn't model this without a
    # FastAPI/pydantic plugin.
    message: str = ...,  # type: ignore[assignment]
) -> JobLogResponse:
    """Create a log entry for a job.

    Used internally by the API and worker to record job lifecycle events.
    """
    # Verify job exists
    await get_job_or_404(db, job_id)

    # Create log entry
    log_entry = JobLog(
        job_id=str(job_id),
        ts=datetime.now(timezone.utc),
        level=level,
        message=message,
    )

    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)

    return JobLogResponse.model_validate(log_entry)


# Global logs response model
class GlobalLogsResponse(BaseModel):
    """Response model for global logs endpoint."""

    logs: list[JobLogResponse] = Field(
        default_factory=list, description="List of log entries"
    )
    total: int = Field(description="Total number of log entries")


@global_logs_router.get("", response_model=GlobalLogsResponse)
async def get_global_logs(
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    job_id: UUID | None = None,
    level_filter: LogLevel | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> GlobalLogsResponse:
    """Get logs across all jobs.

    Returns a paginated list of log entries from all jobs, with optional
    filtering by job_id, log level, and date range.

    Query parameters:
    - job_id: Filter logs for a specific job
    - level_filter: Filter by log level (debug, info, warning, error)
    - since: Start timestamp (inclusive)
    - until: End timestamp (inclusive)
    - limit: Number of logs per page (default 100)
    - offset: Pagination offset (default 0)
    """
    # Build query
    query = select(JobLog)

    # Apply filters
    conditions = []

    if job_id is not None:
        conditions.append(JobLog.job_id == str(job_id))

    if level_filter is not None:
        conditions.append(JobLog.level == level_filter)

    if since is not None:
        conditions.append(JobLog.ts >= since)

    if until is not None:
        conditions.append(JobLog.ts <= until)

    if conditions:
        query = query.where(and_(*conditions))

    # Get total count
    count_query = select(func.count(JobLog.id))
    if conditions:
        count_query = count_query.where(and_(*conditions))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated logs ordered by timestamp descending
    query = query.order_by(desc(JobLog.ts)).limit(limit).offset(offset)
    result = await db.execute(query)
    logs = result.scalars().all()

    return GlobalLogsResponse(
        logs=[JobLogResponse.model_validate(log) for log in logs],
        total=total,
    )


# Export routers
router = jobs_logs_router
