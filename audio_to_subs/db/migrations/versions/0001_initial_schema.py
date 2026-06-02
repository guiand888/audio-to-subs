"""Initial schema for v2.

Revision ID: 0001
Revises: 
Create Date: 2026-06-02 00:00:00.000000

"""

from typing import Any

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create initial tables."""
    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )

    # Jobs table
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True, default=sa.func.uuid4),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("media_path", sa.Text(), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("language_code", sa.String(length=10), nullable=True),
        sa.Column(
            "output_format",
            sa.String(length=20),
            nullable=False,
            server_default="srt",
        ),
        sa.Column("priority", sa.Integer(), nullable=False, default=0),
        sa.Column("progress_percent", sa.Integer(), nullable=False, default=0),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, default=False),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
        sa.Column("mistral_usage_json", sa.Text(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')",
            name="jobs_status_check",
        ),
        sa.CheckConstraint(
            "source IN ('bazarr_movie','bazarr_episode','manual')",
            name="jobs_source_check",
        ),
    )

    # JobLogs table
    op.create_table(
        "job_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "level IN ('debug','info','warning','error')",
            name="job_logs_level_check",
        ),
    )

    # Settings table
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # BazarrCache table
    op.create_table(
        "bazarr_cache",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ext_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("media_path", sa.Text(), nullable=False),
        sa.Column("has_any_subs", sa.Boolean(), nullable=False, default=False),
        sa.Column("missing_subtitles", sa.JSON(), nullable=False, default=[]),
        sa.Column("last_polled", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("active_job_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "kind IN ('movie','episode')",
            name="bazarr_cache_kind_check",
        ),
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("bazarr_cache")
    op.drop_table("settings")
    op.drop_table("job_logs")
    op.drop_table("jobs")
    op.drop_table("users")
