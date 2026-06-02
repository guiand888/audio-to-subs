"""Job claiming for worker queue.

Provides atomic job claiming using SQLite RETURNING clause with BEGIN IMMEDIATE
transaction. This ensures safe concurrent access from multiple workers.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from audio_to_subs.db.models import Job, JobStatus, JobSource, OutputFormat

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class ClaimedJob:
    """A job that has been claimed by a worker.

    Attributes:
        id: Unique job identifier
        media_path: Path to the media file to process
        output_path: Path where output subtitles should be written
        language_code: Optional language code for transcription
        output_format: Output subtitle format
        source: Job source (manual, bazarr_movie, bazarr_episode)
        source_ref: Optional reference to external source (e.g., Bazarr ID)
    """

    id: UUID
    media_path: str
    output_path: str
    language_code: Optional[str]
    output_format: str
    source: str
    source_ref: Optional[str]


def claim_one(
    session: "Session",
    worker_id: str,
    busy_timeout_ms: int = 5000,
) -> Optional[ClaimedJob]:
    """Atomically claim one queued job and mark it as running.

    Uses BEGIN IMMEDIATE + RETURNING for atomicity. Returns None if no jobs
    are available.

    The claim is performed as a single atomic statement:
    - UPDATE jobs SET status='running', worker_id=:worker_id, started_at=NOW
      WHERE id = (SELECT id FROM jobs WHERE status='queued' ORDER BY priority DESC, created_at ASC LIMIT 1)
      RETURNING id, media_path, output_path, language_code, output_format, source, source_ref

    Args:
        session: SQLAlchemy session for database operations
        worker_id: Unique identifier for the claiming worker
        busy_timeout_ms: SQLite busy timeout in milliseconds (default: 5000)

    Returns:
        ClaimedJob if a job was claimed, None if no queued jobs available
    """
    from sqlalchemy import update, and_, or_

    try:
        # Set busy timeout for WAL mode concurrent access
        session.execute(text(f"PRAGMA busy_timeout = {busy_timeout_ms}"))

        # Atomic claim: update the oldest highest-priority queued job and return it
        # Using a subquery to select the job in the WHERE clause
        claim_stmt = text("""
            UPDATE jobs
            SET
                status = 'running',
                worker_id = :worker_id,
                started_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                progress_percent = 0,
                progress_message = 'Starting job processing'
            WHERE id IN (
                SELECT id FROM jobs
                WHERE status = 'queued'
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            )
            RETURNING id, media_path, output_path, language_code, output_format, source, source_ref
        """)

        result = session.execute(
            claim_stmt,
            {"worker_id": worker_id},
        )

        row = result.fetchone()
        if row is None:
            return None

        # Commit the claim
        session.commit()

        return ClaimedJob(
            id=UUID(row[0]),
            media_path=row[1],
            output_path=row[2] if row[2] else "",
            language_code=row[3],
            output_format=row[4],
            source=row[5],
            source_ref=row[6],
        )

    except IntegrityError:
        # Handle any integrity errors
        session.rollback()
        return None
    except Exception as e:
        session.rollback()
        raise
