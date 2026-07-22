"""Tests for admin bootstrap."""

import pytest

from audio_to_subs.auth.bootstrap import bootstrap_admin
from audio_to_subs.db.session import get_async_session, init_db

# One in-memory DSN per test: init_db sets up the engine cache, then
# get_async_session returns the same cached engine so schema and queries
# share the same StaticPool connection.
_TEST_DSN = "sqlite+aiosqlite:///:memory:"


async def test_bootstrap_admin_creates_user():
    """Test that bootstrap_admin creates admin user when database is empty."""
    import audio_to_subs.db.base as db_base

    db_base._async_engines.pop(_TEST_DSN, None)  # start fresh so init_db owns the cache

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        result = await bootstrap_admin(
            session,
            username="admin",
            password="admin123",
        )

        assert result is True

        from sqlalchemy import select

        from audio_to_subs.db.models import User

        rows = (await session.execute(select(User))).scalars().all()
        assert len(rows) == 1
        assert rows[0].username == "admin"
        assert rows[0].password_hash is not None


async def test_bootstrap_admin_skips_existing_user():
    """Test that bootstrap_admin does not create a duplicate user when one
    already exists and the resolved secret matches the stored hash (no
    reconcile needed)."""
    import audio_to_subs.db.base as db_base
    from audio_to_subs.auth.passwords import hash_password
    from audio_to_subs.db.models import User

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        existing_user = User(
            username="existing",
            password_hash=hash_password("password"),
        )
        session.add(existing_user)
        await session.commit()

        result = await bootstrap_admin(
            session,
            username="admin",
            password="password",
        )

        assert result is False

        from sqlalchemy import select

        rows = (await session.execute(select(User))).scalars().all()
        assert len(rows) == 1
        assert rows[0].username == "existing"


async def test_bootstrap_admin_refuses_without_credentials():
    """Test that bootstrap_admin raises ValueError when no credentials and empty DB."""
    import audio_to_subs.db.base as db_base

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        with pytest.raises(ValueError, match="ADMIN_USERNAME/ADMIN_PASSWORD not set"):
            await bootstrap_admin(session)


async def test_bootstrap_admin_refuses_without_password():
    """Test that bootstrap_admin raises ValueError when only username provided."""
    import audio_to_subs.db.base as db_base

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        with pytest.raises(ValueError, match="ADMIN_USERNAME/ADMIN_PASSWORD not set"):
            await bootstrap_admin(session, username="admin")


async def test_bootstrap_admin_refuses_placeholder_password():
    """M6 security: bootstrap must refuse a default/placeholder admin password
    (the shipped docker-compose uses ADMIN_PASSWORD=admin)."""
    import audio_to_subs.db.base as db_base

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        with pytest.raises(ValueError, match="placeholder admin password"):
            await bootstrap_admin(session, username="admin", password="admin")


async def test_bootstrap_admin_refuses_empty_password():
    """M6 security: an empty admin password is also rejected as a placeholder."""
    import audio_to_subs.db.base as db_base

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        with pytest.raises(ValueError, match="placeholder admin password"):
            await bootstrap_admin(session, username="admin", password="")


# --- M10: startup reconcile of the admin password on secret/env change ---


async def test_bootstrap_admin_reconciles_changed_password():
    """Existing admin + a resolved secret that no longer matches the stored
    hash → the hash is updated in place and the function reports a change."""
    import audio_to_subs.db.base as db_base
    from audio_to_subs.auth.passwords import hash_password, verify_password
    from audio_to_subs.db.models import User

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        existing_user = User(
            username="admin",
            password_hash=hash_password("old-secure-password-1"),
        )
        session.add(existing_user)
        await session.commit()

        result = await bootstrap_admin(
            session,
            username="admin",
            password="new-secure-password-2",
        )

        assert result is True

        from sqlalchemy import select

        rows = (await session.execute(select(User))).scalars().all()
        assert len(rows) == 1
        assert verify_password("new-secure-password-2", rows[0].password_hash)
        assert not verify_password("old-secure-password-1", rows[0].password_hash)


async def test_bootstrap_admin_reconcile_noop_when_password_unchanged():
    """Existing admin + a resolved secret that still matches the stored hash
    → the hash is left untouched and the function reports no change."""
    import audio_to_subs.db.base as db_base
    from audio_to_subs.auth.passwords import hash_password
    from audio_to_subs.db.models import User

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        existing_user = User(
            username="admin",
            password_hash=hash_password("same-secure-password-1"),
        )
        session.add(existing_user)
        await session.commit()
        stored_hash_before = existing_user.password_hash

        result = await bootstrap_admin(
            session,
            username="admin",
            password="same-secure-password-1",
        )

        assert result is False

        from sqlalchemy import select

        rows = (await session.execute(select(User))).scalars().all()
        assert len(rows) == 1
        assert rows[0].password_hash == stored_hash_before


async def test_bootstrap_admin_reconcile_noop_when_password_none():
    """Existing admin + password=None (secret unset/file absent) must be a
    pure no-op — never lock the operator out over an unrelated secret
    rotation (e.g. rotating SESSION_SECRET while ADMIN_PASSWORD_FILE is
    absent)."""
    import audio_to_subs.db.base as db_base
    from audio_to_subs.auth.passwords import hash_password
    from audio_to_subs.db.models import User

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        existing_user = User(
            username="admin",
            password_hash=hash_password("existing-secure-password-1"),
        )
        session.add(existing_user)
        await session.commit()
        stored_hash_before = existing_user.password_hash

        result = await bootstrap_admin(session, username="admin", password=None)

        assert result is False

        from sqlalchemy import select

        rows = (await session.execute(select(User))).scalars().all()
        assert len(rows) == 1
        assert rows[0].password_hash == stored_hash_before


async def test_bootstrap_admin_reconcile_refuses_placeholder_and_keeps_stored_hash():
    """A secret rotated TO a placeholder value must be refused, and the
    stored hash must stay untouched (operator is not silently downgraded to a
    known/public credential)."""
    import audio_to_subs.db.base as db_base
    from audio_to_subs.auth.passwords import hash_password, verify_password
    from audio_to_subs.db.models import User

    db_base._async_engines.pop(_TEST_DSN, None)

    await init_db(_TEST_DSN)

    async with get_async_session(_TEST_DSN) as session:
        existing_user = User(
            username="admin",
            password_hash=hash_password("existing-secure-password-1"),
        )
        session.add(existing_user)
        await session.commit()

        with pytest.raises(ValueError, match="placeholder"):
            await bootstrap_admin(session, username="admin", password="admin")

        from sqlalchemy import select

        rows = (await session.execute(select(User))).scalars().all()
        assert len(rows) == 1
        # Stored hash is untouched: the old password still verifies, and the
        # placeholder was never persisted.
        assert verify_password("existing-secure-password-1", rows[0].password_hash)
        assert not verify_password("admin", rows[0].password_hash)
