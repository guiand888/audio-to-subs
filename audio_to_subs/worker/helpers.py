"""Helpers for worker database operations."""

import logging
from typing import Any, Callable, TypeVar

from sqlalchemy.exc import IntegrityError

if False:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def execute_and_commit(
    session: "AsyncSession",
    operation: Callable[..., Any],
    operation_name: str,
    job_id: Any,
) -> None:
    """Execute a database operation and commit.

    Handles common try/except/rollback pattern for DB operations.

    Args:
        session: Async database session
        operation: Async callable that performs DB operations (e.g., session.execute)
        operation_name: Name of the operation for logging
        job_id: Job ID for error logging context
    """
    try:
        await operation()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.warning(f"Integrity error during {operation_name} for job {job_id}")
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to {operation_name} for job {job_id}: {e}")
