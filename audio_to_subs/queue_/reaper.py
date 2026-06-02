"""Job reaper for crash recovery.

Requeues jobs that have been running without progress updates beyond the stale
threshold. This handles worker crashes and allows jobs to be picked up by other workers.
"""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from sqlalchemy import text, and_
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def reap_stale_running(
    session: "Session",
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
        # Set busy timeout for WAL mode concurrent access
        session.execute(text(f"PRAGMA busy_timeout = {busy_timeout_ms}"))

        # Compute the stale threshold
        stale_threshold = datetime.utcnow() - timedelta(seconds=stale_seconds)

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
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'running'
              AND updated_at < :stale_threshold
            RETURNING id
        """)

        result = session.execute(
            reap_stmt,
            {"stale_threshold": stale_threshold.isoformat()},
        )

        reaped_ids = [row[0] for row in result.fetchall()]
        count = len(reaped_ids)

        if count > 0:
            session.commit()
            logger.info(f"Reaped {count} stale running jobs: {reaped_ids}")
        else:
            session.rollback()

        return count

    except IntegrityError:
        session.rollback()
        logger.error("Integrity error during reaping")
        return 0
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to reap stale jobs: {e}")
        raise
