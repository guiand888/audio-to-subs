"""Add overwrite flag and the active-job duplicate guard to jobs.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-12 00:00:00.000000

M6.g (Overwrite & duplicate-job guards):
- `overwrite` column (bool, default false) threaded from the API through to
  the worker so an explicit re-transcribe can replace an existing subtitle.
- A partial UNIQUE index over (media_path, COALESCE(language_code, ''),
  output_format) WHERE status IN ('queued','running'). The COALESCE wraps
  language_code so auto-detect jobs (NULL language_code) are still
  deduplicated — a plain (media_path, language_code, output_format) index
  would treat two NULLs as distinct and let duplicate auto jobs through.
- create_job_service turns the resulting IntegrityError into a 409
  `job_already_active`; the worker's write-time guard turns an existing
  output file into a FAILED job with an `output_exists` error.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "overwrite",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Partial unique index enforcing at most one active (queued/running) job
    # per (media_path, language_code, output_format). COALESCE collapses NULL
    # language_code (auto-detect jobs) to '' so they participate in the guard.
    op.create_index(
        "ix_jobs_active_dupguard",
        "jobs",
        [
            sa.text("media_path"),
            sa.text("COALESCE(language_code, '')"),
            sa.text("output_format"),
        ],
        unique=True,
        sqlite_where=sa.text("status IN ('queued','running')"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_active_dupguard", table_name="jobs")
    op.drop_column("jobs", "overwrite")
