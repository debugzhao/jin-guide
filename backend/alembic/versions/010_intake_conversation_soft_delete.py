"""Intake conversation soft delete

Revision ID: 010
Revises: 009
Create Date: 2026-07-16

Changes:
1. 新增 intake_conversations.deleted_at（nullable）——支持会话重命名/删除
   （Phase 2），软删除对齐 reports/documents 表的既有约定
   （backend/docs/03_data_model.md §4）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "intake_conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("intake_conversations", "deleted_at")
