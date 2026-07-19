"""Shared helper for writing to the job_logs activity log.

job_logs backs the UI-visible activity log (/api/logs, /api/jobs/{id}/logs
and the frontend's Logs/History pages) - a small, curated set of
user-facing milestones and failures, not a mirror of every logger call.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from audio_to_subs.db.models import JobLog, LogLevel

logger = logging.getLogger(__name__)


async def write_job_log(
    session: AsyncSession,
    level: LogLevel,
    message: str,
    job_id: str | None = None,
) -> None:
    """Write an entry to the job_logs activity log.

    Best-effort: failures are logged but never raised, so a logging failure
    can never break the caller's action.

    Args:
        session: Async database session
        level: Log level (debug/info/warning/error)
        message: Human-readable message shown in the UI
        job_id: Associated job, or None for a global (non-job-scoped) entry
    """
    try:
        log_entry = JobLog(
            job_id=str(job_id) if job_id is not None else None,
            ts=datetime.now(timezone.utc),
            level=level,
            message=message,
        )
        session.add(log_entry)
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to write job log (job_id={job_id}): {e}")
