"""删除旧的 messages_json 列

Revision ID: 016
Revises: 015
Create Date: 2026-07-24

Changes (docs/memory-architecture.md 第六节 P2, 停旧写阶段):
1. 应用层已经完全停止读写 report_conversations.messages_json /
   intake_conversations.messages_json ——`014` 建了 conversation_messages/
   conversation_summaries 两张新表，`015` 把历史数据回填进去，随后
   get_or_create_conversation_row（原 upsert_conversation_row）不再往这两个
   JSONB 列写任何内容，两个 GET history 端点也都改成从 conversation_messages
   读取。这一步删掉列本身，完成"双写 → 回填 → 切读 → 停旧写"四阶段迁移的最后
   一步。
2. downgrade 会把列加回来但是空数组默认值——旧数据已经在 015 回填进
   conversation_messages，此处不做反向回填，和 009 迁移里对不可逆 downgrade
   的处理方式一致。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("report_conversations", "messages_json")
    op.drop_column("intake_conversations", "messages_json")


def downgrade() -> None:
    op.add_column(
        "intake_conversations",
        sa.Column("messages_json", postgresql.JSONB, server_default="[]", nullable=False),
    )
    op.add_column(
        "report_conversations",
        sa.Column("messages_json", postgresql.JSONB, server_default="[]", nullable=False),
    )
