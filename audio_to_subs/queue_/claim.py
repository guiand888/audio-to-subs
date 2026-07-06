"""Job claiming for worker queue.

Provides atomic job claiming using SQLite RETURNING clause with BEGIN IMMEDIATE
transaction. This ensures safe concurrent access from multiple workers.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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


async def claim_one(
    session: "AsyncSession",
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

    try:
        # Atomic claim: update the oldest highest-priority queued job and return it
        # Using a subquery to select the job in the WHERE clause
        claim_stmt = text(
            """
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
        """
        )

        result = await session.execute(
            claim_stmt,
            {"worker_id": worker_id},
        )

        row = result.fetchone()
        if row is None:
            # No job available: release the write lock the UPDATE acquired
            # immediately, otherwise the idle loop would monopolise SQLite's
            # single writer and starve every other writer.
            await session.rollback()
            return None

        # Commit the claim
        await session.commit()

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
        await session.rollback()
        return None
    except Exception:
        await session.rollback()
        raise
