"""Wanted API routes for Bazarr integration."""

import logging
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from audio_to_subs.api.deps import SettingsDep, get_db
from audio_to_subs.bazarr.pathmap import PathMap
from audio_to_subs.db.models import BazarrCache, Job, JobStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wanted", tags=["wanted"])


class WantedItemType(str, Enum):
    ALL = "all"
    MOVIE = "movie"
    EPISODE = "episode"


class WantedItem(BaseModel):
    """Wanted item with job status."""

    model_config = {"from_attributes": True}

    id: str = Field(description="Cache ID (e.g., 'movie:123' or 'episode:456')")
    kind: str = Field(description="Item kind: 'movie' or 'episode'")
    ext_id: int = Field(description="External ID (Radarr or Sonarr ID)")
    title: str = Field(description="Item title")
    media_path: str = Field(description="Translated media file path")
    has_any_subs: bool = Field(description="Whether item has any subtitles")
    missing_subtitles: list[dict] = Field(
        default_factory=list, description="List of missing subtitles"
    )
    audio_language: list[dict] = Field(
        default_factory=list,
        description="Audio languages Bazarr reports for this item",
    )
    last_polled: datetime = Field(description="When this item was last polled")
    active_job_id: str | None = Field(
        default=None, description="ID of active job for this item"
    )
    active_job_status: str | None = Field(
        default=None, description="Status of active job if present"
    )
    active_job_progress: int | None = Field(
        default=None, description="Progress percent of active job"
    )


class WantedListResponse(BaseModel):
    """Response for wanted items list."""

    items: list[WantedItem] = Field(description="List of wanted items")
    total: int = Field(description="Total count of items")
    last_refreshed_at: datetime | None = Field(
        default=None, description="When the cache was last refreshed"
    )


async def _get_path_map(db: "AsyncSession") -> PathMap:
    """Get PathMap from database settings."""
    return await PathMap.load_from_db(db)


async def _translate_paths(
    db: "AsyncSession",
    items: list[BazarrCache],
) -> list[BazarrCache]:
    """Translate media paths using path mappings.

    Args:
        db: Database session
        items: List of BazarrCache items

    Returns:
        List of items with translated paths
    """
    path_map = await _get_path_map(db)

    for item in items:
        if item.media_path:
            item.media_path = path_map.translate(item.media_path)

    return items


async def _get_last_refreshed(db: "AsyncSession") -> datetime | None:
    """Get the most recent poll time from cache.

    Args:
        db: Database session

    Returns:
        Most recent last_polled timestamp or None
    """
    result = await db.execute(select(func.max(BazarrCache.last_polled)))
    max_polled = result.scalar_one_or_none()
    return max_polled if max_polled else None


def _to_wanted_item(
    item: BazarrCache,
    active_job_status: str | None,
    active_job_progress: int | None,
) -> WantedItem:
    """Build a WantedItem response from a BazarrCache row plus job status.

    Args:
        item: BazarrCache row (with path already translated)
        active_job_status: Status of the item's active job, if any
        active_job_progress: Progress percent of the item's active job, if any

    Returns:
        Assembled WantedItem
    """
    return WantedItem(
        id=item.id,
        kind=item.kind,
        ext_id=item.ext_id,
        title=item.title,
        media_path=item.media_path,
        has_any_subs=item.has_any_subs,
        missing_subtitles=item.missing_subtitles,
        audio_language=item.audio_language,
        last_polled=item.last_polled,
        active_job_id=str(item.active_job_id) if item.active_job_id else None,
        active_job_status=active_job_status,
        active_job_progress=active_job_progress,
    )


@router.get("", response_model=WantedListResponse)
async def list_wanted(  # noqa: C901
    db: Annotated["AsyncSession", Depends(get_db)],
    item_type: WantedItemType = Query(  # noqa: B008
        default=WantedItemType.ALL, description="Filter by item type"
    ),
    language: str | None = Query(
        default=None, description="Filter by missing language code"
    ),
    has_job: bool | None = Query(
        default=None, description="Filter by whether item has an active job"
    ),
    page: int = Query(default=1, ge=1, description="Page number"),  # noqa: B008
    page_size: int = Query(
        default=100, ge=1, le=1000, description="Items per page"
    ),  # noqa: B008
) -> WantedListResponse:
    """List wanted items from Bazarr cache.

    Returns filtered, paginated list of items that are missing subtitles.
    Never hits Bazarr directly - reads from local cache only.

    Query parameters:
    - item_type: Filter by type (all, movie, episode)
    - language: Filter by specific missing language code
    - has_job: Filter by whether item has an active job (true/false)
    - page: Page number (1-based)
    - page_size: Items per page
    """
    # Build base query
    query = select(BazarrCache).order_by(desc(BazarrCache.last_polled))

    # Apply type filter
    if item_type != WantedItemType.ALL:
        query = query.where(BazarrCache.kind == item_type.value)

    # Note: Language filter applied in Python below (SQLite has no json_contains)

    # Apply has_job filter
    if has_job is not None:
        if has_job:
            query = query.where(BazarrCache.active_job_id.is_not(None))
        else:
            query = query.where(BazarrCache.active_job_id.is_(None))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    result = await db.execute(count_query)
    total = result.scalar_one()

    # Get paginated items
    offset = (page - 1) * page_size
    query = query.limit(page_size).offset(offset)
    result = await db.execute(query)
    items = result.scalars().all()

    # Filter by language if specified (Python-side since SQLite lacks json_contains)
    if language:
        filtered_items = []
        for item in items:
            if item.missing_subtitles:
                for sub in item.missing_subtitles:
                    if isinstance(sub, dict) and sub.get("code2") == language:
                        filtered_items.append(item)
                        break
        items = filtered_items

    # Translate paths
    items = await _translate_paths(db, items)

    # Batch-load active job status/progress for all items in one query
    # (avoids one SELECT per item).
    active_job_ids = [item.active_job_id for item in items if item.active_job_id]
    jobs_by_id: dict[str, tuple[str, int | None]] = {}
    if active_job_ids:
        job_result = await db.execute(
            select(Job.id, Job.status, Job.progress_percent)
            .where(Job.id.in_(active_job_ids))
            .where(Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        )
        jobs_by_id = {
            job_id: (job_status, progress_percent)
            for job_id, job_status, progress_percent in job_result.all()
        }

    # Get active job status for each item
    wanted_items: list[WantedItem] = []
    for item in items:
        active_job_status = None
        active_job_progress = None

        if item.active_job_id:
            job_info = jobs_by_id.get(item.active_job_id)
            if job_info:
                active_job_status, active_job_progress = job_info

        wanted_items.append(
            _to_wanted_item(item, active_job_status, active_job_progress)
        )

    # Get last refreshed time
    last_refreshed = await _get_last_refreshed(db)

    return WantedListResponse(
        items=wanted_items,
        total=total,
        last_refreshed_at=last_refreshed,
    )


@router.get("/{item_id}", response_model=WantedItem)
async def get_wanted_item(
    item_id: str,
    db: Annotated["AsyncSession", Depends(get_db)],
) -> WantedItem:
    """Get a specific wanted item by ID.

    Args:
        item_id: Cache ID (e.g., 'movie:123' or 'episode:456')

    Returns:
        Wanted item details
    """
    result = await db.execute(select(BazarrCache).where(BazarrCache.id == item_id))
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wanted item {item_id} not found",
        )

    # Translate path
    item = (await _translate_paths(db, [item]))[0]

    # Get active job status
    active_job_status = None
    active_job_progress = None

    if item.active_job_id:
        job_result = await db.execute(
            select(Job.status, Job.progress_percent)
            .where(Job.id == item.active_job_id)
            .where(Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        )
        job = job_result.one_or_none()
        if job:
            # job.status is stored as string in DB (Mapped[JobStatus] over String(20))
            active_job_status = job.status
            active_job_progress = job.progress_percent

    return _to_wanted_item(item, active_job_status, active_job_progress)


# Refresh endpoint models
class WantedRefreshRequest(BaseModel):
    """Request model for wanted list refresh."""

    item_type: WantedItemType = Field(
        default=WantedItemType.ALL,
        description="Filter by item type: all, movie, or episode",
    )


class WantedRefreshResponse(BaseModel):
    """Response model for wanted list refresh."""

    status: str = Field(description="Refresh status: started, completed, failed")
    movies_processed: int = Field(default=0, description="Number of movies processed")
    episodes_processed: int = Field(
        default=0, description="Number of episodes processed"
    )
    error: str | None = Field(default=None, description="Error message if failed")


@router.post(
    "/refresh",
    response_model=WantedRefreshResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_wanted_list(
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: SettingsDep,
    refresh_request: WantedRefreshRequest = Body(  # noqa: B008
        default_factory=WantedRefreshRequest
    ),
) -> WantedRefreshResponse:
    """Trigger a manual refresh of the wanted list from Bazarr.

    This endpoint triggers an immediate poll of Bazarr for wanted items,
    respecting the filtering scope specified in the request.

    The refresh:
    - Uses database settings first, falling back to environment variables
    - Respects the item_type filter (all, movies, episodes)
    - Respects the bazarr_track_no_subs setting
    - Updates the local cache with fresh data from Bazarr
    - Returns counts of items processed

    Args:
        item_type: Filter scope - "all" polls both movies and episodes,
                   "movie" polls only movies, "episode" polls only episodes

    Returns:
        Refresh result with status and counts
    """
    from audio_to_subs.bazarr.poller import (
        get_bazarr_client_with_settings,
        get_path_map,
        poll_bazarr_manually,
    )

    try:
        # Get Bazarr client using database settings first, then environment fallback
        client, bazarr_url, bazarr_api_key, bazarr_timeout = (
            await get_bazarr_client_with_settings(db, settings)
        )
    except Exception as e:
        logger.error("Failed to initialize Bazarr client: %s", type(e).__name__)
        return WantedRefreshResponse(
            status="failed",
            movies_processed=0,
            episodes_processed=0,
            error="Bazarr client initialization failed",
        )

    if client is None:
        return WantedRefreshResponse(
            status="failed",
            movies_processed=0,
            episodes_processed=0,
            error="Bazarr not configured",
        )

    # Everything from here on must close the client on every exit path,
    # including failures in get_path_map (not just poll_bazarr_manually).
    try:
        path_map = await get_path_map(db)

        movies_processed, episodes_processed = await poll_bazarr_manually(
            db, client, path_map, refresh_request.item_type.value
        )

        return WantedRefreshResponse(
            status="completed",
            movies_processed=movies_processed,
            episodes_processed=episodes_processed,
            error=None,
        )

    except Exception as e:
        logger.error("Failed to refresh wanted list: %s", type(e).__name__)
        return WantedRefreshResponse(
            status="failed",
            movies_processed=0,
            episodes_processed=0,
            error="Refresh failed",
        )
    finally:
        await client.close()
