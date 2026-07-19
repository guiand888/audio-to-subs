"""History API routes for completed jobs."""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, desc, func, select

from audio_to_subs.api.deps import get_db
from audio_to_subs.api.routes.jobs import JobResponse
from audio_to_subs.db.models import Job, JobSource, JobStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/history", tags=["history"])


# Response models
class HistoryStats(BaseModel):
    """Aggregate statistics for history."""

    total_jobs: int = Field(description="Total number of completed jobs")
    total_cost_usd: float = Field(description="Total cost across all jobs")
    total_audio_length_seconds: float = Field(
        description="Total audio track length across all jobs"
    )
    total_runtime_seconds: float = Field(
        description="Total job wall-clock processing time across all jobs"
    )
    average_cost_usd: float = Field(description="Average cost per job")
    average_audio_length_seconds: float = Field(
        description="Average audio track length per job"
    )
    average_runtime_seconds: float = Field(
        description="Average job wall-clock processing time per job"
    )
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


@router.get("", response_model=HistoryResponse)
async def get_history(
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    status_filter: list[JobStatus] | None = Query(default=None),  # noqa: B008
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
    count_query = select(func.count(Job.id)).where(Job.status.in_(statuses_to_query))
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
    conditions: list[Any],
) -> HistoryStats:
    """Calculate aggregate statistics for history jobs.

    Args:
        db: Database session
        statuses: List of job statuses to include
        conditions: Additional filter conditions

    Returns:
        HistoryStats with all aggregate calculations
    """
    # Base query filters
    base_where: ColumnElement[bool] = Job.status.in_(statuses)
    if conditions:
        base_where = and_(base_where, and_(*conditions))

    # Get total count, sum of costs, sum of audio length, and sum of runtime.
    # ``costed_jobs`` counts only jobs that actually incurred a cost (the
    # worker sets estimated_cost_usd solely on success, so FAILED/CANCELLED
    # jobs are NULL and excluded). Using a filtered aggregate keeps it in the
    # same single query and stays symmetric with SUM (which ignores NULLs).
    totals_query = select(
        func.count(Job.id).label("total_jobs"),
        func.sum(Job.estimated_cost_usd).label("total_cost_usd"),
        func.sum(Job.audio_duration_seconds).label("total_audio_length_seconds"),
        func.sum(
            (func.julianday(Job.finished_at) - func.julianday(Job.started_at)) * 86400.0
        ).label("total_runtime_seconds"),
        func.count(Job.id)
        .filter(Job.estimated_cost_usd.isnot(None))
        .label("costed_jobs"),
    ).where(base_where)

    totals_result = await db.execute(totals_query)
    totals_row = totals_result.one()
    total_jobs = totals_row.total_jobs or 0
    total_cost = float(totals_row.total_cost_usd or 0.0)
    total_audio_length = float(totals_row.total_audio_length_seconds or 0.0)
    total_runtime = float(totals_row.total_runtime_seconds or 0.0)
    costed_jobs = totals_row.costed_jobs or 0

    if total_jobs == 0:
        return HistoryStats(
            total_jobs=0,
            total_cost_usd=0.0,
            total_audio_length_seconds=0.0,
            total_runtime_seconds=0.0,
            average_cost_usd=0.0,
            average_audio_length_seconds=0.0,
            average_runtime_seconds=0.0,
        )

    # Get counts by status using GROUP BY
    status_query = (
        select(
            Job.status,
            func.count(Job.id).label("count"),
        )
        .where(base_where)
        .group_by(Job.status)
    )

    status_result = await db.execute(status_query)
    count_by_status: dict[str, int] = {
        (status_val.value if hasattr(status_val, "value") else str(status_val)): count
        for status_val, count in status_result.all()
    }

    # Get counts by language using GROUP BY
    language_query = (
        select(
            Job.language_code,
            func.count(Job.id).label("count"),
        )
        .where(base_where)
        .where(Job.language_code.isnot(None))
        .group_by(Job.language_code)
    )

    language_result = await db.execute(language_query)
    # language_code is filtered to isnot(None) in language_query above, so
    # str(...) here is a type-narrowing no-op, never a real "None" string.
    count_by_language: dict[str, int] = {
        str(language_code): count for language_code, count in language_result.all()
    }

    # Get counts by source using GROUP BY
    source_query = (
        select(
            Job.source,
            func.count(Job.id).label("count"),
        )
        .where(base_where)
        .group_by(Job.source)
    )

    source_result = await db.execute(source_query)
    count_by_source: dict[str, int] = {
        (source_val.value if hasattr(source_val, "value") else str(source_val)): count
        for source_val, count in source_result.all()
    }

    return HistoryStats(
        total_jobs=total_jobs,
        total_cost_usd=round(total_cost, 4),
        total_audio_length_seconds=round(total_audio_length, 2),
        total_runtime_seconds=round(total_runtime, 2),
        average_cost_usd=round(total_cost / costed_jobs, 4) if costed_jobs > 0 else 0.0,
        average_audio_length_seconds=(
            round(total_audio_length / total_jobs, 2) if total_jobs > 0 else 0.0
        ),
        average_runtime_seconds=(
            round(total_runtime / total_jobs, 2) if total_jobs > 0 else 0.0
        ),
        count_by_status=count_by_status,
        count_by_language=count_by_language,
        count_by_source=count_by_source,
    )
