"""province_thresholds：新增 max_volunteers 列

Revision ID: 006
Revises: 005
Create Date: 2026-07-09

变更：
1. province_thresholds：新增 max_volunteers 整数列（默认 96），让各省份的志愿表
   条数上限（CLAUDE.md「志愿数上限」约束）由这张表驱动，而不是硬编码在
   app/api/v1/data.py 里的 96。
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
