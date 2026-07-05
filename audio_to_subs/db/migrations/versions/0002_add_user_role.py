"""Add role column to users table.

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add role column with default value
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="user"))


def downgrade() -> None:
    # Remove role column
    op.drop_column("users", "role")
