"""History API routes for completed jobs."""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import joinedload

from audio_to_subs.api.deps import get_db
from audio_to_subs.db.models import Job, JobStatus, JobSource

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/history", tags=["history"])


# Response models
class HistoryStats(BaseModel):
    """Aggregate statistics for history."""

    total_jobs: int = Field(description="Total number of completed jobs")
    total_cost_usd: float = Field(description="Total cost across all jobs")
    total_duration_seconds: float = Field(description="Total audio duration across all jobs")
    average_cost_usd: float = Field(description="Average cost per job")
    average_duration_seconds: float = Field(description="Average duration per job")
    count_by_status: dict[str, int] = Field(
        description="Count of jobs by status", default_factory=dict
    )
    count_by_language: dict[str, int] = Field(
        description="Count of jobs by language", default_factory=dict
    )
    count_by_source: dict[str, int] = Field(
        description="Count of jobs by source", default_factory=dict
    )


class HistoryResponse(BaseModel):
    """Response model for history endpoint."""

    jobs: list["JobResponse"] = Field(default_factory=list, description="List of jobs")
    stats: HistoryStats = Field(description="Aggregate statistics")
    total: int = Field(description="Total number of jobs (pre-pagination)")
    limit: int = Field(description="Pagination limit")
    offset: int = Field(description="Pagination offset")


# Import JobResponse from jobs.py to reuse it
from audio_to_subs.api.routes.jobs import JobResponse


@router.get("", response_model=HistoryResponse)
async def get_history(
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    status_filter: list[JobStatus] | None = None,
    source_filter: JobSource | None = None,
    language_filter: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> HistoryResponse:
    """Get history of completed jobs with aggregate statistics.

    Returns completed jobs (done, failed, cancelled) with pagination and
    aggregate cost/duration statistics. Supports filtering by status,
    source, language, and date range.

    Query parameters:
    - status_filter: Comma-separated list of statuses (done,failed,cancelled)
    - source_filter: Filter by source (bazarr_movie, bazarr_episode, manual)
    - language_filter: Filter by language code
    - since: Start date (inclusive)
    - until: End date (inclusive)
    - limit: Number of jobs per page (default 100)
    - offset: Pagination offset (default 0)
    """
    # Default statuses for history: terminal states
    terminal_statuses = [JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED]

    # If status_filter provided, use that; otherwise use all terminal statuses
    if status_filter:
        statuses_to_query = status_filter
    else:
        statuses_to_query = terminal_statuses

    # Build query for jobs
    query = select(Job).where(Job.status.in_(statuses_to_query))

    # Apply filters
    conditions = []

    if source_filter is not None:
        conditions.append(Job.source == source_filter)

    if language_filter is not None:
        conditions.append(Job.language_code == language_filter)

    if since is not None:
        conditions.append(Job.created_at >= since)

    if until is not None:
        conditions.append(Job.created_at <= until)

    if conditions:
        query = query.where(and_(*conditions))

    # Get total count before pagination
    count_query = select(func.count(Job.id)).where(
        Job.status.in_(statuses_to_query)
    )
    if conditions:
        count_query = count_query.where(and_(*conditions))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated jobs ordered by created_at descending
    query = query.order_by(desc(Job.created_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    jobs = result.scalars().all()

    # Calculate aggregate statistics
    stats = await _calculate_stats(db, statuses_to_query, conditions)

    return HistoryResponse(
        jobs=[JobResponse.model_validate(job) for job in jobs],
        stats=stats,
        total=total,
        limit=limit,
        offset=offset,
    )


async def _calculate_stats(
    db: "AsyncSession",
    statuses: list[JobStatus],
    conditions: list,
) -> HistoryStats:
    """Calculate aggregate statistics for history jobs.

    Args:
        db: Database session
        statuses: List of job statuses to include
        conditions: Additional filter conditions

    Returns:
        HistoryStats with all aggregate calculations
    """
    from sqlalchemy import case, cast, Float, Integer

    # Base query for completed jobs
    query = select(Job).where(Job.status.in_(statuses))
    if conditions:
        query = query.where(and_(*conditions))

    # Get all matching jobs for stats
    result = await db.execute(query)
    all_jobs = result.scalars().all()

    if not all_jobs:
        return HistoryStats(
            total_jobs=0,
            total_cost_usd=0.0,
            total_duration_seconds=0.0,
            average_cost_usd=0.0,
            average_duration_seconds=0.0,
        )

    # Calculate totals
    total_cost = 0.0
    total_duration = 0.0
    count_by_status: dict[str, int] = {}
    count_by_language: dict[str, int] = {}
    count_by_source: dict[str, int] = {}

    for job in all_jobs:
        # Cost
        if job.estimated_cost_usd is not None:
            total_cost += job.estimated_cost_usd

        # Duration
        if job.audio_duration_seconds is not None:
            total_duration += job.audio_duration_seconds

        # Count by status — SQLAlchemy returns raw strings for String(20) columns;
        # use .value when the attribute holds an enum, fall back to str() otherwise.
        status_str = job.status.value if hasattr(job.status, "value") else str(job.status)
        count_by_status[status_str] = count_by_status.get(status_str, 0) + 1

        # Count by language
        if job.language_code:
            count_by_language[job.language_code] = (
                count_by_language.get(job.language_code, 0) + 1
            )

        # Count by source
        source_str = job.source.value if hasattr(job.source, "value") else str(job.source)
        count_by_source[source_str] = count_by_source.get(source_str, 0) + 1

    num_jobs = len(all_jobs)

    return HistoryStats(
        total_jobs=num_jobs,
        total_cost_usd=round(total_cost, 4),
        total_duration_seconds=round(total_duration, 2),
        average_cost_usd=round(total_cost / num_jobs, 4) if num_jobs > 0 else 0.0,
        average_duration_seconds=round(total_duration / num_jobs, 2)
        if num_jobs > 0
        else 0.0,
        count_by_status=count_by_status,
        count_by_language=count_by_language,
        count_by_source=count_by_source,
    )
