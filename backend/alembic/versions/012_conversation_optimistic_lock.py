"""Conversation optimistic lock version column

Revision ID: 012
Revises: 011
Create Date: 2026-07-24

Changes:
1. 新增 report_conversations.version / intake_conversations.version（默认 0，
   not null）——配合 SQLAlchemy version_id_col 做乐观锁，修复两个并发请求同时
   追加同一会话历史时，后写请求整体覆盖丢失先写请求内容的问题。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "report_conversations",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "intake_conversations",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("intake_conversations", "version")
    op.drop_column("report_conversations", "version")
