"""Admin user bootstrap.

Creates the initial admin user on first boot, and on every subsequent boot
reconciles its password against the resolved secret (startup reconcile
trigger model — see M10).
"""

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from audio_to_subs.auth.passwords import hash_password, verify_password

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default/placeholder admin passwords that must never be used in production.
# The shipped docker-compose sets ADMIN_PASSWORD=admin as a placeholder; the
# bootstrap must refuse to start with any of these so a real secret is set.
PLACEHOLDER_ADMIN_PASSWORDS: frozenset[str] = frozenset(
    {
        "changeme",
        "password",
        "admin",
        "root",
        "123456",
        "",
    }
)


async def bootstrap_admin(
    db: "AsyncSession",
    username: str | None = None,
    password: str | None = None,
) -> bool:
    """Bootstrap admin user, or reconcile its password with the resolved secret.

    Called on every startup (not just first boot). If no user exists yet, the
    admin user is created from ``username``/``password``. If a user already
    exists, this reconciles its stored password hash against the currently
    resolved secret (ADMIN_PASSWORD / ADMIN_PASSWORD_FILE): when they differ,
    the hash is rotated to match, so a Podman secret or .env rotation takes
    effect automatically on the next redeploy — no explicit operator action
    required.

    A ``password`` of ``None`` (secret unset / file absent) is always treated
    as a no-op on the reconcile path: an operator rotating an unrelated
    secret (e.g. SESSION_SECRET) while ADMIN_PASSWORD_FILE happens to be
    absent must never be locked out as a side effect.

    Args:
        db: Async database session
        username: Admin username (from env)
        password: Admin password (from env)

    Returns:
        True if the admin user was created or its password was reconciled to
        a new value, False if nothing changed (already up to date, or
        password is None).

    Raises:
        ValueError: If database is empty and no credentials provided, or if
            the resolved password (first-boot or reconcile) is a known
            default/placeholder value.
    """
    from audio_to_subs.db.models import User

    # Check if any users exist
    result = await db.execute(select(User).limit(1))
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        if password is None:
            # Secret unset/file absent: never treat this as "rotate to
            # nothing" — an unrelated secret rotation must not lock out the
            # operator.
            logger.info("Admin user already exists, password unchanged")
            return False

        if verify_password(password, existing_user.password_hash):
            logger.info("Admin user already exists, password unchanged")
            return False

        if password in PLACEHOLDER_ADMIN_PASSWORDS:
            raise ValueError(
                "Refusing to rotate admin password to a default or placeholder "
                "value. Set ADMIN_PASSWORD (or ADMIN_PASSWORD_FILE) to a "
                "strong secret."
            )

        # Resolved secret changed since last boot: reconcile the stored hash.
        # No commit here for the same reason as the create path below — the
        # caller owns the transaction/commit.
        existing_user.password_hash = hash_password(password)
        await db.flush()
        logger.info(
            "Reconciled admin password for '%s' from updated secret",
            existing_user.username,
        )
        return True

    # No users exist - need credentials
    if username is None or password is None:
        raise ValueError(
            "No users exist and ADMIN_USERNAME/ADMIN_PASSWORD not set. "
            "Set ADMIN_USERNAME and ADMIN_PASSWORD (or ADMIN_PASSWORD_FILE) "
            "in the environment or Podman secret to create the admin user."
        )

    # Refuse to bootstrap with a default/placeholder admin password (M6
    # security pass). The shipped docker-compose uses ADMIN_PASSWORD=admin as
    # a placeholder; starting with it would expose the app with known creds.
    if password in PLACEHOLDER_ADMIN_PASSWORDS:
        raise ValueError(
            "Refusing to bootstrap with a default or placeholder admin password. "
            "Set ADMIN_PASSWORD (or ADMIN_PASSWORD_FILE) to a strong secret."
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
