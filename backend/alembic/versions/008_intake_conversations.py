"""建档前聊天会话

Revision ID: 008
Revises: 007
Create Date: 2026-07-14

Changes:
1. New table: intake_conversations — Chat-first 建档前聊天历史冷层兜底存储
   （owner_key 是 user_id 或 anonymous_id 二选一，还没有 report_id 可挂靠）
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intake_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_key", sa.String(36), nullable=False, unique=True),
        # {role, content, created_at} 组成的 JSONB 列表——应用层负责限制最多 50 条消息
        sa.Column(
            "messages_json", postgresql.JSONB, server_default="[]", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_intake_conversations_owner_key", "intake_conversations", ["owner_key"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_intake_conversations_owner_key", table_name="intake_conversations"
    )
    op.drop_table("intake_conversations")
