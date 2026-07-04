"""Job reaper for crash recovery.

Requeues jobs that have been running without progress updates beyond the stale
threshold. This handles worker crashes and allows jobs to be picked up by other workers.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import text, and_
from sqlalchemy.exc import IntegrityError

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
        # Calculate the cutoff timestamp
        cutoff = datetime.now(timezone.utc) - stale_threshold

        # Delete done/failed jobs that are stale
        # Only delete non-active jobs to avoid losing work
        delete_stmt = text("""
            DELETE FROM jobs
            WHERE status IN ('done', 'failed', 'cancelled')
              AND updated_at < :cutoff
        """)

        result = await session.execute(
            delete_stmt,
            {"cutoff": cutoff.isoformat()},
        )

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
        # Compute the stale threshold
        stale_threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Atomic reaping statement
        # Only requeue jobs that are still in 'running' state and haven't been updated recently
        reap_stmt = text("""
            UPDATE jobs
            SET
                status = 'queued',
                worker_id = NULL,
                progress_percent = 0,
                progress_message = 'Requeued after worker restart',
                started_at = NULL,
                updated_at = :now
            WHERE status = 'running'
              AND updated_at < :stale_threshold
            RETURNING id
        """)

        result = await session.execute(
            reap_stmt,
            {"stale_threshold": stale_threshold.isoformat(), "now": now_iso},
        )

        reaped_ids = [row[0] for row in result.fetchall()]
        count = len(reaped_ids)

        if count > 0:
            await session.commit()
            logger.info(f"Reaped {count} stale running jobs: {reaped_ids}")
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
