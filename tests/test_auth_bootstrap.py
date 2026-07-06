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
    """Test that bootstrap_admin skips when user already exists."""
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
            password="admin123",
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
