"""Add provenance/status fields to student_profiles and preferences

Revision ID: 017
Revises: 016
Create Date: 2026-07-28

Changes (docs/memory-architecture.md 第六节 P4 第 1 步——只加字段/迁移，不接任何
提取/确认逻辑，见该节"解决方案"分阶段落地节奏第 1 步):
1. `preferences` 表原本连 `created_at`/`updated_at` 都没有（见 P4"现状"表格），
   先补上这两列，否则后面的 provenance 字段无法回填、也无法回答"这条偏好是什么
   时候记录的"。
2. `student_profiles`/`preferences` 各再加 6 列：
   - source_type：user_explicit / model_inferred，标记这条记录是用户明确填写/
     表达的，还是 AI 从对话推断的（目前唯一写入路径是表单提交，历史数据和新增
     行都恒为 user_explicit，model_inferred 是给未来 Chat 提取链路预留的取值）
   - confidence：置信度，仅 model_inferred 记录有意义，user_explicit 恒为 NULL
   - status：confirmed / proposed / rejected / superseded，对齐
     docs/memory-architecture.md §5.4 的状态机；表单提交视为即时确认，恒为
     confirmed
   - last_confirmed_at：最后一次被确认的时间；回填为 created_at（表单提交本身
     就是一次显式确认）
   - source_message_id：如果来源于某条对话消息，指向 conversation_messages.id；
     表单提交场景下恒为 NULL
   - superseded_by / superseded_at：自引用，标记这条记录被哪条新记录取代、何时
     取代——用于保留"同一偏好改过多次"的历史链条而不是直接覆盖（见 P4 验收标准
     "历史可追溯性"）
3. 本迁移只加列、不改变任何现有读写路径——`app/api/v1/profile.py` 的
   create_profile/get_profile 暂不使用这些新列，等 P4 第 2 步接入方案 B 最小链路
   （用户在聊天里明确表达 + 显式确认后才写 proposed→confirmed）时再使用。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("student_profiles", "preferences")


def upgrade() -> None:
    op.add_column(
        "preferences",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "preferences",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("source_type", sa.String(20), nullable=False, server_default="user_explicit"),
        )
        op.add_column(table, sa.Column("confidence", sa.Float(), nullable=True))
        op.add_column(
            table,
            sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"),
        )
        op.add_column(table, sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "source_message_id",
                sa.String(36),
                sa.ForeignKey("conversation_messages.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(table, sa.Column("superseded_by", sa.String(36), nullable=True))
        op.add_column(table, sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_superseded_by",
            table,
            table,
            ["superseded_by"],
            ["id"],
            ondelete="SET NULL",
        )
        # 历史数据是表单一次性提交产生的，视为提交时刻即已确认
        op.execute(f"UPDATE {table} SET last_confirmed_at = created_at")


def downgrade() -> None:
    for table in _TABLES:
        op.drop_constraint(f"fk_{table}_superseded_by", table, type_="foreignkey")
        op.drop_column(table, "superseded_at")
        op.drop_column(table, "superseded_by")
        op.drop_column(table, "source_message_id")
        op.drop_column(table, "last_confirmed_at")
        op.drop_column(table, "status")
        op.drop_column(table, "confidence")
        op.drop_column(table, "source_type")

    op.drop_column("preferences", "updated_at")
    op.drop_column("preferences", "created_at")
