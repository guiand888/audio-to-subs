"""Tests for admin bootstrap."""

import pytest

from audio_to_subs.auth.bootstrap import bootstrap_admin


@pytest.mark.asyncio
async def test_bootstrap_admin_creates_user():
    """Test that bootstrap_admin creates admin user when database is empty."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from audio_to_subs.db.base import Base
    from audio_to_subs.db.models import User
    from audio_to_subs.db.session import get_async_session
    
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        # Bootstrap should create user
        result = await bootstrap_admin(
            session,
            username="admin",
            password="admin123",
        )
        
        assert result is True
        
        # Check user was created
        from sqlalchemy import select
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        assert len(users) == 1
        assert users[0].username == "admin"
        assert users[0].password_hash is not None


@pytest.mark.asyncio
async def test_bootstrap_admin_skips_existing_user():
    """Test that bootstrap_admin skips when user already exists."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from audio_to_subs.db.base import Base
    from audio_to_subs.db.models import User
    from audio_to_subs.auth.passwords import hash_password
    from audio_to_subs.db.session import get_async_session
    
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        # Create existing user
        existing_user = User(
            username="existing",
            password_hash=hash_password("password"),
        )
        session.add(existing_user)
        await session.commit()
        
        # Bootstrap should skip
        result = await bootstrap_admin(
            session,
            username="admin",
            password="admin123",
        )
        
        assert result is False
        
        # Check only existing user
        from sqlalchemy import select
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        assert len(users) == 1
        assert users[0].username == "existing"


@pytest.mark.asyncio
async def test_bootstrap_admin_refuses_without_credentials():
    """Test that bootstrap_admin raises ValueError when no credentials and empty DB."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from audio_to_subs.db.base import Base
    from audio_to_subs.db.session import get_async_session
    
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        # Bootstrap should raise
        with pytest.raises(ValueError, match="ADMIN_USERNAME/ADMIN_PASSWORD not set"):
            await bootstrap_admin(session)


@pytest.mark.asyncio
async def test_bootstrap_admin_refuses_without_password():
    """Test that bootstrap_admin raises ValueError when only username provided."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from audio_to_subs.db.base import Base
    from audio_to_subs.db.session import get_async_session
    
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        # Bootstrap should raise
        with pytest.raises(ValueError, match="ADMIN_USERNAME/ADMIN_PASSWORD not set"):
            await bootstrap_admin(session, username="admin")
