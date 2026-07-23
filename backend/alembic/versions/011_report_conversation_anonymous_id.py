"""Report conversation anonymous_id

Revision ID: 011
Revises: 010
Create Date: 2026-07-23

Changes:
1. 新增 report_conversations.anonymous_id（nullable）——修复所有匿名用户共享
   user_id IS NULL 导致同一份报告下不同匿名人互相读到对方问答历史的串读问题。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "report_conversations",
        sa.Column("anonymous_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("report_conversations", "anonymous_id")
