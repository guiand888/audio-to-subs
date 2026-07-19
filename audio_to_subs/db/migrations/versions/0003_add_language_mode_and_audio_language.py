"""Add language_mode/detected-language tracking to jobs and audio_language to bazarr_cache.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-08 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "language_mode", sa.String(10), nullable=False, server_default="explicit"
        ),
    )
    op.add_column(
        "jobs", sa.Column("mistral_detected_language", sa.String(10), nullable=True)
    )
    op.add_column(
        "jobs",
        sa.Column(
            "needs_language_review",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "bazarr_cache",
        sa.Column("audio_language", sa.JSON, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("bazarr_cache", "audio_language")
    op.drop_column("jobs", "needs_language_review")
    op.drop_column("jobs", "mistral_detected_language")
    op.drop_column("jobs", "language_mode")
