"""Progress bridge for worker job execution.

Bridges pipeline structured progress events to:
1. Database updates (debounced to ~1Hz)
2. Redis pub/sub notifications
3. Job log entries on stage transitions
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from audio_to_subs.core.cancel import CancelToken
from audio_to_subs.core.pipeline import ProgressEvent
from audio_to_subs.db.models import JobLog, LogLevel
from audio_to_subs.db.session import get_async_session
from audio_to_subs.queue_.events import publish_progress

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Debounce interval in seconds
DB_UPDATE_DEBOUNCE = 1.0


@dataclass
class ProgressBridge:
    """Bridges pipeline progress events to external systems.

    Uses per-write sessions to avoid concurrent coroutine access to a shared
    AsyncSession, which is not thread-safe. A lock serializes writes to SQLite.

    Attributes:
        database_url: Database connection URL for per-write sessions
        redis: Redis async client
        job_id: UUID of the job being processed
        token: Cancellation token for the job
        loop: Event loop for scheduling async operations
    """

    database_url: str
    redis: "Redis"
    job_id: UUID
    token: CancelToken
    loop: "asyncio.AbstractEventLoop"

    _last_percent: int = field(default=0, init=False)
    _last_db_update: float = field(default=0.0, init=False)
    _last_stage: Optional[str] = field(default=None, init=False)
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def on_event(self, event: ProgressEvent) -> None:
        """Synchronous progress callback for the pipeline.

        The pipeline runs in a worker thread (via asyncio.to_thread) and invokes
        this callback synchronously. DB and Redis writes must happen on the
        event loop, so we marshal the async handler back onto it. Fire-and-forget
        is intentional: progress is best-effort and must never block or break the
        job; the debounce + lock in ``_handle`` keep writes ordered and
        rate-limited.
        """
        asyncio.run_coroutine_threadsafe(self._handle(event), self.loop)

    async def _handle(self, event: ProgressEvent) -> None:
        """Handle a structured progress event from the pipeline.

        Performs the following actions:
        1. Updates job row in DB with progress (debounced to ~1Hz)
        2. Publishes progress to Redis channels
        3. Writes to job_logs on stage transitions

        Args:
            event: Structured progress event from pipeline
        """
        try:
            # Extract event data
            percent = event.get("percent", 0)
            stage = event.get("stage", "unknown")
            message = event.get("message", "")

            # Publish to Redis immediately (cheap, no debouncing needed)
            await publish_progress(
                self.redis,
                str(self.job_id),
                percent,
                stage,
                message,
            )

            # Capture the previous stage before any updates below can change it,
            # so the stage-transition check isn't comparing stage against itself.
            previous_stage = self._last_stage

            # Update DB with progress (debounced)
            current_time = time.monotonic()
            if (
                percent != self._last_percent
                or stage != previous_stage
                or current_time - self._last_db_update >= DB_UPDATE_DEBOUNCE
            ):
                await self._update_job_progress(percent, stage, message)
                self._last_percent = percent
                self._last_db_update = current_time
                self._last_stage = stage

            # Write to job_logs on stage transitions
            if stage != previous_stage:
                await self._write_job_log(stage, message)
                self._last_stage = stage

        except Exception as e:
            logger.error(f"Error handling progress event for job {self.job_id}: {e}")
            # Don't raise - progress updates should never break the job

    async def _update_job_progress(
        self, percent: int, stage: str, message: str
    ) -> None:
        """Update job progress in database using a per-write session."""
        async with self._write_lock:
            try:
                async with get_async_session(self.database_url) as session:
                    update_stmt = text(
                        """
                        UPDATE jobs
                        SET
                            progress_percent = :percent,
                            progress_message = :message,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :job_id
                    """
                    )
                    await session.execute(
                        update_stmt,
                        {
                            "percent": percent,
                            "message": message,
                            "job_id": str(self.job_id),
                        },
                    )
                    await session.commit()
            except IntegrityError:
                logger.warning(
                    f"Integrity error updating progress for job {self.job_id}"
                )
            except Exception as e:
                logger.error(f"Failed to update progress for job {self.job_id}: {e}")

    async def _write_job_log(self, stage: str, message: str) -> None:
        """Write a log entry for stage transition using a per-write session."""
        async with self._write_lock:
            try:
                async with get_async_session(self.database_url) as session:
                    log_entry = JobLog(
                        job_id=str(self.job_id),
                        ts=datetime.now(timezone.utc),
                        level=LogLevel.INFO,
                        message=f"[{stage}] {message}",
                    )
                    session.add(log_entry)
                    await session.commit()
            except Exception as e:
                logger.error(f"Failed to write job log for job {self.job_id}: {e}")

    async def close(self) -> None:
        """Clean up resources."""
        pass
