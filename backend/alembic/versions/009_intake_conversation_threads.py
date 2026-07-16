"""Intake conversation threads

Revision ID: 009
Revises: 008
Create Date: 2026-07-16

Changes:
1. intake_conversations.owner_key 去掉 unique 约束——从"每人一条历史"改为
   "每人多条会话"（多会话历史，`id` 即会话/thread id）。
2. 新增 intake_conversations.title（nullable）——首条用户消息截断生成，供
   侧栏会话列表展示。
3. 新增复合索引 (owner_key, updated_at, id)，配合会话列表的游标分页查询
   （按 owner_key 过滤 + updated_at desc, id desc 排序）。
4. owner_key 从 varchar(36) 加宽到 varchar(48)——修复一个预先存在的 bug：
   匿名会话的 owner_key 是 `"anon:" + 36 位 uuid`（41 字符），超出原
   varchar(36) 上限，写入时被 asyncpg 抛 StringDataRightTruncationError，
   又被 `_persist_history_to_db` 的 best-effort try/except 悄悄吞掉——
   实际后果是匿名用户的建档聊天历史从未真正落过 Postgres 冷层，只靠
   Redis 7 天 TTL 硬撑。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "intake_conversations_owner_key_key", "intake_conversations", type_="unique"
    )
    op.alter_column(
        "intake_conversations",
        "owner_key",
        existing_type=sa.String(36),
        type_=sa.String(48),
    )
    op.add_column(
        "intake_conversations", sa.Column("title", sa.String(100), nullable=True)
    )
    op.create_index(
        "ix_intake_conversations_owner_key_updated_at",
        "intake_conversations",
        ["owner_key", "updated_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_intake_conversations_owner_key_updated_at",
        table_name="intake_conversations",
    )
    op.drop_column("intake_conversations", "title")
    op.alter_column(
        "intake_conversations",
        "owner_key",
        existing_type=sa.String(48),
        type_=sa.String(36),
    )
    # 注意：如果 downgrade 时已有同一 owner_key 的多条会话，这个约束会创建失败，
    # 需要先手动合并/清理多余的行。
    op.create_unique_constraint(
        "intake_conversations_owner_key_key", "intake_conversations", ["owner_key"]
    )
