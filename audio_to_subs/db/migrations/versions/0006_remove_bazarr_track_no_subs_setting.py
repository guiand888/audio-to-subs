"""Remove the obsolete bazarr_track_no_subs setting row.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-22 00:00:00.000000

M8 (full library sync) made the bazarr_track_no_subs setting redundant —
the 3-way scope (all / missing / no_subs) is now derived at query time
from the wanted cache. The setting was removed from DEFAULT_SETTINGS and
the response/update models, but existing deployments still carry the row
in the settings table. This migration deletes the orphaned row so upgraded
DBs match fresh installs.

The downgrade re-inserts the row with its pre-M8 default (False) for
operators who roll back, matching the value in DEFAULT_SETTINGS on
origin/main.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'bazarr_track_no_subs'")


def downgrade() -> None:
    op.execute(
        "INSERT INTO settings (key, value_json) "
        "VALUES ('bazarr_track_no_subs', 'false')"
    )
