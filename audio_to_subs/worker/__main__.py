"""Worker entry point.

Runs as a background process that claims jobs from the queue and executes
them through the pipeline. Progress updates are published via Redis and stored
in the database.

Usage:
    python -m audio_to_subs.worker

Environment variables:
    DATABASE_URL: Database connection URL (default: sqlite+aiosqlite:////data/audio-to-subs.db)
    REDIS_URL: Redis connection URL (default: redis://localhost:6379/0)
    MISTRAL_API_KEY: Mistral API key (or MISTRAL_API_KEY_FILE)
    WORKER_ID: Optional worker identifier (auto-generated if not provided)
"""

import asyncio
import logging
import os
import signal
import socket
import uuid
from typing import Any

from redis.asyncio import Redis

from audio_to_subs.api.settings import Settings, get_settings
from audio_to_subs.db.session import get_async_session
from audio_to_subs.queue_.claim import claim_one
from audio_to_subs.queue_.reaper import reap_stale_running
from audio_to_subs.worker.runner import run_job, WorkerDeps, JobResult
from audio_to_subs.worker.progress import ProgressBridge

logger = logging.getLogger(__name__)


class Worker:
    """Background worker for job processing."""

    def __init__(self) -> None:
        """Initialize worker."""
        self._settings: Settings | None = None
        self._redis: Redis | None = None
        self._shutdown = False
        self._worker_id: str = self._generate_worker_id()

    def _generate_worker_id(self) -> str:
        """Generate a unique worker identifier."""
        env_worker_id = os.environ.get("WORKER_ID")
        if env_worker_id:
            return env_worker_id
        return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"

    async def startup(self) -> None:
        """Initialize worker dependencies."""
        logger.info(f"Worker {self._worker_id} starting up...")

        # Load settings
        self._settings = get_settings()

        # Initialize Redis
        self._redis = Redis.from_url(self._settings.REDIS_URL)
        await self._redis.ping()
        logger.info("Redis connected")

        # Run reaper on startup to clean up any stale jobs
        async with get_async_session(self._settings.DATABASE_URL) as session:
            reaped = reap_stale_running(session, stale_seconds=120)
            logger.info(f"Reaper cleanup: {reaped} stale jobs requeued")

    async def shutdown(self) -> None:
        """Clean up worker resources."""
        logger.info(f"Worker {self._worker_id} shutting down...")
        if self._redis:
            await self._redis.close()
        self._shutdown = True

    async def claim_and_run(self) -> None:
        """Claim a job and run it.

        This is the main worker loop:
        1. Try to claim a job
        2. If claimed, run it
        3. If no job available, wait for notification
        """
        if self._settings is None or self._redis is None:
            raise RuntimeError("Worker not started. Call startup() first.")

        while not self._shutdown:
            try:
                async with get_async_session(self._settings.DATABASE_URL) as session:
                    # Try to claim a job
                    claimed = claim_one(session, self._worker_id)

                    if claimed is not None:
                        logger.info(
                            f"Worker {self._worker_id} claimed job {claimed.id}"
                        )

                        # Get Mistral API key
                        mistral_api_key = self._settings.mistral_api_key
                        if mistral_api_key is None:
                            logger.error(
                                "MISTRAL_API_KEY not configured. Cannot run job."
                            )
                            # Mark job as failed
                            await self._mark_job_failed(
                                session, claimed.id, "Missing Mistral API key"
                            )
                            continue

                        # Build worker deps
                        deps = WorkerDeps(
                            session=session,
                            redis=self._redis,
                            settings=self._settings,
                            mistral_api_key=mistral_api_key,
                        )

                        # Run the job
                        result = await run_job(claimed, deps)

                        # Persist result
                        await self._persist_job_result(session, claimed.id, result)

                        logger.info(
                            f"Worker {self._worker_id} completed job {claimed.id}: {result.status}"
                        )

                    else:
                        # No job available, wait briefly before retrying
                        logger.debug(
                            f"Worker {self._worker_id} waiting for jobs..."
                        )
                        await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Worker {self._worker_id} error: {e}")
                await asyncio.sleep(1)

    async def _mark_job_failed(
        self, session: Any, job_id: Any, error_message: str
    ) -> None:
        """Mark a job as failed in the database."""
        from sqlalchemy import text

        update_stmt = text(
            "UPDATE jobs SET status='failed', finished_at=CURRENT_TIMESTAMP, "
            "error_message=:error WHERE id=:id"
        )
        await session.execute(update_stmt, {"error": error_message, "id": str(job_id)})
        await session.commit()

    async def _persist_job_result(
        self, session: Any, job_id: Any, result: JobResult
    ) -> None:
        """Persist job result to database."""
        from sqlalchemy import text

        update_fields = {
            "status": result.status.value,
            "finished_at": "CURRENT_TIMESTAMP",
            "updated_at": "CURRENT_TIMESTAMP",
        }

        if result.error_message:
            update_fields["error_message"] = result.error_message
        if result.audio_duration_seconds is not None:
            update_fields["audio_duration_seconds"] = result.audio_duration_seconds
        if result.mistral_usage_json is not None:
            update_fields["mistral_usage_json"] = result.mistral_usage_json
        if result.estimated_cost_usd is not None:
            update_fields["estimated_cost_usd"] = result.estimated_cost_usd

        set_clause = ", ".join([f"{k} = :{k}" for k in update_fields.keys()])
        update_stmt = text(f"UPDATE jobs SET {set_clause} WHERE id = :job_id")

        params = {**update_fields, "job_id": str(job_id)}
        await session.execute(update_stmt, params)
        await session.commit()

    async def run(self) -> None:
        """Main worker loop."""
        await self.startup()
        try:
            while not self._shutdown:
                await self.claim_and_run()
        finally:
            await self.shutdown()


def handle_shutdown(worker: Worker) -> None:
    """Handle shutdown signals."""
    def shutdown(signame: str) -> None:
        logger.info(f"Received signal {signame}, shutting down...")
        worker._shutdown = True

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)


async def main() -> None:
    """Worker entry point."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    worker = Worker()
    handle_shutdown(worker)

    try:
        await worker.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
