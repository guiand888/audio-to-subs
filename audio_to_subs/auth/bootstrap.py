"""Admin user bootstrap.

Creates initial admin user on first boot.
"""

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from audio_to_subs.auth.passwords import hash_password

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def bootstrap_admin(
    db: "AsyncSession",
    username: str | None = None,
    password: str | None = None,
) -> bool:
    """Bootstrap admin user if database is empty.

    Args:
        db: Async database session
        username: Admin username (from env)
        password: Admin password (from env)

    Returns:
        True if admin was created, False if already exists

    Raises:
        ValueError: If database is empty and no credentials provided
    """
    from audio_to_subs.db.models import User

    # Check if any users exist
    result = await db.execute(select(User).limit(1))
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        logger.info("Admin user already exists, skipping bootstrap")
        return False

    # No users exist - need credentials
    if username is None or password is None:
        raise ValueError(
            "No users exist and ADMIN_USERNAME/ADMIN_PASSWORD not set. "
            "Run 'python -m audio_to_subs.admin set-password' to create admin."
        )

    # Create admin user.
    #
    # Do NOT commit here: bootstrap_admin() is called with a caller-owned
    # session (typically inside `async with get_async_session(...)`, which
    # commits once on successful exit). Committing here too would be a
    # redundant second commit for the same unit of work. We still need an
    # explicit flush (not a commit) so the row is persistent within the
    # transaction before `db.refresh()`, which requires the instance to
    # already have an identity.
    password_hash = hash_password(password)
    admin = User(
        username=username,
        password_hash=password_hash,
    )
    db.add(admin)
    await db.flush()
    await db.refresh(admin)

    logger.info("Bootstrapped admin user '%s' from env", username)
    return True
