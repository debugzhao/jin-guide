"""province_thresholds: add max_volunteers column

Revision ID: 006
Revises: 005
Create Date: 2026-07-09

Changes:
1. province_thresholds: add max_volunteers Integer column (default 96) so the
   per-province volunteer table cap (CLAUDE.md「志愿数上限」约束) is driven by
   this table instead of a hardcoded 96 in app/api/v1/data.py.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "province_thresholds",
        sa.Column("max_volunteers", sa.Integer, nullable=False, server_default="96"),
    )


def downgrade() -> None:
    op.drop_column("province_thresholds", "max_volunteers")
