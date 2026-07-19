"""Progress bridge for worker job execution.

Bridges pipeline structured progress events to:
1. Redis pub/sub notifications (live SSE stream)
2. A Redis progress snapshot hash (REST polling read path)
3. Job log entries on stage transitions (debounced SQLite writes)

In-flight progress is written to Redis only — the DB progress_* columns are
written once, at terminal state, by worker/runner.persist_result. This keeps
the high-frequency, ephemeral progress stream off the relational store
(important under SQLite's single-writer lock and at multi-pod SaaS scale).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from audio_to_subs.core.cancel import CancelToken
from audio_to_subs.core.pipeline import ProgressEvent
from audio_to_subs.db.models import JobLog, LogLevel
from audio_to_subs.db.session import get_async_session
from audio_to_subs.queue_.events import (
    publish_progress,
    set_job_progress,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass
class ProgressBridge:
    """Bridges pipeline progress events to external systems.

    Uses per-write sessions to avoid concurrent coroutine access to a shared
    AsyncSession, which is not thread-safe. A lock serializes writes to SQLite.

    Attributes:
        database_url: Database connection URL for per-write sessions
        redis: Redis async client
        job_id: String job id of the job being processed
        token: Cancellation token for the job
        loop: Event loop for scheduling async operations
    """

    database_url: str
    redis: "Redis"
    job_id: str
    token: CancelToken
    loop: "asyncio.AbstractEventLoop"

    _last_stage: Optional[str] = field(default=None, init=False)
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    # Redis snapshot write debounce (carried over from the old DB write): we
    # refresh the live-progress hash at most once per SNAPSHOT_MIN_INTERVAL and
    # whenever the percent/stage changes, so a chatty pipeline can't flood
    # Redis with no-op HSETs. The SSE pub/sub publish below stays immediate.
    _snapshot_min_interval: float = field(default=1.0, init=False)
    _last_snapshot_at: float = field(default=0.0, init=False)
    _last_snapshot_key: Optional[str] = field(default=None, init=False)

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
        1. Publishes progress to Redis pub/sub (drives the live SSE stream)
        2. Mirrors progress into a Redis hash (drives the REST polling read
           path via GET /api/jobs)
        3. Writes to job_logs on stage transitions (infrequent, debounced)

        In-flight progress is intentionally NOT written to the DB here — the
        relational store is only updated at terminal state by
        worker/runner.persist_result. This keeps the per-event progress stream
        off SQLite's single writer (and off the DB entirely at SaaS scale).

        Args:
            event: Structured progress event from pipeline
        """
        try:
            # Extract event data
            percent = event.get("percent", 0)
            stage = event.get("stage", "unknown")
            message = event.get("message", "")
            step_index = event.get("step_index")
            step_total = event.get("step_total")

            # Publish to Redis pub/sub immediately (cheap, drives the SSE stream).
            await publish_progress(
                self.redis,
                str(self.job_id),
                percent,
                stage,
                message,
                step_index=step_index,
                step_total=step_total,
            )

            # Mirror into the Redis progress snapshot (drives GET /api/jobs
            # polling). This is the authoritative live-progress store now.
            # Debounce: write immediately on percent/stage change or once per
            # SNAPSHOT_MIN_INTERVAL, otherwise skip — the SSE pub/sub above is
            # always immediate, so the live stream is unaffected.
            snapshot_key = f"{percent}:{stage}"
            now = time.monotonic()
            if (
                snapshot_key != self._last_snapshot_key
                or now - self._last_snapshot_at >= self._snapshot_min_interval
            ):
                await set_job_progress(
                    self.redis,
                    str(self.job_id),
                    percent,
                    stage,
                    message,
                    step_index=step_index,
                    step_total=step_total,
                )
                self._last_snapshot_key = snapshot_key
                self._last_snapshot_at = now

            # Capture the previous stage before any updates below can change it,
            # so the stage-transition check isn't comparing stage against itself.
            previous_stage = self._last_stage

            # Write to job_logs on stage transitions (infrequent; the only
            # remaining SQLite write on this path).
            if stage != previous_stage:
                await self._write_job_log(stage, message)
                self._last_stage = stage

        except Exception:
            logger.exception(f"Error handling progress event for job {self.job_id}")
            # Don't raise - progress updates should never break the job

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
            except Exception:
                logger.exception(f"Failed to write job log for job {self.job_id}")

    async def close(self) -> None:
        """Clean up resources."""
        pass
