"""Job reaper for crash recovery.

Requeues jobs that have been running without progress updates beyond the stale
threshold. This handles worker crashes and allows jobs to be picked up by other workers.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from audio_to_subs.db.models import Job

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def delete_stale_jobs(
    session: "AsyncSession",
    stale_threshold: timedelta,
) -> int:
    """Delete job records that are stale and no longer running.

    Args:
        session: SQLAlchemy async session for database operations
        stale_threshold: timedelta; jobs updated before (now - stale_threshold) are deleted

    Returns:
        Number of jobs deleted
    """
    try:
        # Calculate the cutoff timestamp. Using the ORM delete() construct
        # (rather than a raw SQL string with a manually-formatted timestamp)
        # lets SQLAlchemy's DateTime bind processor format `cutoff` exactly
        # the way it formats every other DateTime column write, so the
        # string comparison SQLite performs underneath is correct. A prior
        # version compared updated_at against cutoff.isoformat() (produces
        # "...T...+00:00"), while ORM writes store "... " (space, no tz) —
        # since ' ' sorts before 'T', that made the predicate true for any
        # same-day row regardless of actual elapsed time.
        cutoff = datetime.now(timezone.utc) - stale_threshold

        delete_stmt = (
            delete(Job)
            .where(Job.status.in_(["done", "failed", "cancelled"]))
            .where(Job.updated_at < cutoff)
        )

        result = await session.execute(delete_stmt)

        deleted_count = result.rowcount
        if deleted_count > 0:
            await session.commit()
            logger.info(f"Deleted {deleted_count} stale job records")
        else:
            await session.rollback()

        return deleted_count

    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to delete stale jobs: {e}")
        raise


async def reap_stale_running(
    session: "AsyncSession",
    stale_seconds: int = 120,
    busy_timeout_ms: int = 5000,
) -> int:
    """Requeue jobs that have been running without updates for stale_seconds.

    Executes an UPDATE to reset running jobs that haven't been updated recently:
    - status -> 'queued'
    - worker_id -> NULL
    - progress_percent -> 0
    - progress_message -> 'Requeued after worker restart'
    - updated_at -> CURRENT_TIMESTAMP

    Args:
        session: SQLAlchemy session for database operations
        stale_seconds: Number of seconds without update before considering job stale (default: 120)
        busy_timeout_ms: SQLite busy timeout in milliseconds (default: 5000)

    Returns:
        Number of jobs that were reaped

    Raises:
        Exception: If database operations fail
    """
    try:
        # Compute the stale threshold. As in delete_stale_jobs, bind the
        # cutoff as a real datetime through the ORM update() construct so
        # SQLAlchemy's DateTime bind processor formats it the same way as
        # every other DateTime write/comparison — a raw text() query here
        # previously compared against stale_threshold.isoformat() (T
        # separator + UTC offset), which does not sort correctly against
        # ORM-stored "YYYY-MM-DD HH:MM:SS.ffffff" values.
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(seconds=stale_seconds)

        reap_stmt = (
            update(Job)
            .where(Job.status == "running")
            .where(Job.updated_at < stale_threshold)
            .values(
                status="queued",
                worker_id=None,
                progress_percent=0,
                progress_message="Requeued after worker restart",
                started_at=None,
                updated_at=now,
            )
        )

        result = await session.execute(reap_stmt)

        count = result.rowcount

        if count > 0:
            await session.commit()
            logger.info(f"Reaped {count} stale running jobs")
        else:
            await session.rollback()

        return count

    except IntegrityError:
        await session.rollback()
        logger.error("Integrity error during reaping")
        return 0
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to reap stale jobs: {e}")
        raise
