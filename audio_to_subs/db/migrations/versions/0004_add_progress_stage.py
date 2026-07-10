"""Add persisted progress stage/step tracking to jobs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-10 00:00:00.000000

M5.8 (#4, verified): adds progress_stage / progress_step_index /
progress_step_total (nullable) so a hard refresh mid-job can reconstruct the
step/stage instead of only percent + free-text message. Written by
worker/progress.py's _update_job_progress and surfaced via JobResponse + the
SSE progress payload.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("progress_stage", sa.String(20), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("progress_step_index", sa.Integer, nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("progress_step_total", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "progress_step_total")
    op.drop_column("jobs", "progress_step_index")
    op.drop_column("jobs", "progress_stage")
