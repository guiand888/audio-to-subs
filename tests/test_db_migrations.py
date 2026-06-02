"""Tests for database migrations."""

import os
import tempfile

import pytest


class TestAlembicConfig:
    """Test Alembic configuration."""

    def test_alembic_ini_exists(self):
        """Test that alembic.ini exists."""
        assert os.path.exists("alembic.ini")

    def test_migrations_directory_exists(self):
        """Test that migrations directory exists."""
        assert os.path.exists("audio_to_subs/db/migrations")

    def test_env_py_exists(self):
        """Test that env.py exists."""
        assert os.path.exists("audio_to_subs/db/migrations/env.py")

    def test_versions_directory_exists(self):
        """Test that versions directory exists."""
        assert os.path.exists("audio_to_subs/db/migrations/versions")

    def test_initial_migration_exists(self):
        """Test that initial migration exists."""
        assert os.path.exists("audio_to_subs/db/migrations/versions/0001_initial_schema.py")


@pytest.mark.asyncio
async def test_migration_can_be_applied():
    """Test that migration can be applied to a fresh database."""
    import subprocess
    import tempfile
    
    # Create temp file for database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    try:
        # Run alembic upgrade head
        result = subprocess.run(
            [
                "alembic",
                "-c", "alembic.ini",
                "upgrade", "head",
            ],
            capture_output=True,
            text=True,
            cwd=".",
            env={
                **os.environ,
                "DATABASE_URL": f"sqlite:///{db_path}",
            },
        )
        
        # Check that migration succeeded
        assert result.returncode == 0, f"Migration failed: {result.stderr}"
        
        # Verify tables exist
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        # Check expected tables exist
        expected_tables = {"users", "jobs", "job_logs", "settings", "bazarr_cache"}
        assert expected_tables.issubset(set(tables))
        
    finally:
        # Cleanup
        os.unlink(db_path)
