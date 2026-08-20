"""会话消息与摘要

Revision ID: 014
Revises: 013
Create Date: 2026-07-24

Changes (docs/memory-architecture.md 第六节 P2):
1. New table: conversation_messages — 追加式消息存储，替代
   report_conversations/intake_conversations.messages_json 整块 JSONB 数组。
   report_conversation_id/intake_conversation_id 二选一（CHECK 约束保证恰好
   一个非空），seq 是同一会话内的递增序号。这是本次拆表的第一步（建表），
   应用层先做双写（旧 messages_json 继续写、同时写这张新表），验证一致后
   再由后续迁移回填历史数据、最终切读并停止旧写。
2. New table: conversation_summaries — 结构化增量摘要（confirmed_facts/
   preferences/rejected_options/previous_decisions/open_questions），覆盖已经
   滑出 Agent 最近消息窗口的历史，随对话增长增量更新，不是每次重新总结全部
   历史。covered_through_seq 记录摘要覆盖到哪条消息为止，供 Agent 侧和下一次
   增量摘要生成共同参照。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "report_conversation_id",
            sa.String(36),
            sa.ForeignKey("report_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "intake_conversation_id",
            sa.String(36),
            sa.ForeignKey("intake_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        # 仅 report_conversation 侧消息使用；intake_conversation 侧恒为 NULL
        sa.Column("citations", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(report_conversation_id IS NULL) != (intake_conversation_id IS NULL)",
            name="ck_conversation_messages_exactly_one_parent",
        ),
        # Postgres 的 UNIQUE 约束里 NULL 互不冲突，所以这两条约束分别只对属于
        # 该类型会话的行生效，不会因为另一类型的行 parent_id 恒为 NULL 而误判冲突
        sa.UniqueConstraint(
            "report_conversation_id", "seq", name="uq_conversation_messages_report_seq"
        ),
        sa.UniqueConstraint(
            "intake_conversation_id", "seq", name="uq_conversation_messages_intake_seq"
        ),
    )
    op.create_index(
        "ix_conversation_messages_report_seq",
        "conversation_messages",
        ["report_conversation_id", "seq"],
    )
    op.create_index(
        "ix_conversation_messages_intake_seq",
        "conversation_messages",
        ["intake_conversation_id", "seq"],
    )

    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "report_conversation_id",
            sa.String(36),
            sa.ForeignKey("report_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "intake_conversation_id",
            sa.String(36),
            sa.ForeignKey("intake_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("summary_json", postgresql.JSONB, nullable=False),
        sa.Column("covered_through_seq", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("source_model", sa.String(50), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("tokens_before", sa.Integer, nullable=True),
        sa.Column("tokens_after", sa.Integer, nullable=True),
        # ready / failed —— failed 表示最近一次生成尝试失败，summary_json 仍是
        # 上一次成功的内容
        sa.Column("status", sa.String(20), nullable=False, server_default="ready"),
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
        sa.CheckConstraint(
            "(report_conversation_id IS NULL) != (intake_conversation_id IS NULL)",
            name="ck_conversation_summaries_exactly_one_parent",
        ),
        # 每个会话至多一条摘要行（NULL 互不冲突，两条约束各自只约束自己类型的会话）
        sa.UniqueConstraint(
            "report_conversation_id", name="uq_conversation_summaries_report"
        ),
        sa.UniqueConstraint(
            "intake_conversation_id", name="uq_conversation_summaries_intake"
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_summaries")
    op.drop_index("ix_conversation_messages_intake_seq", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_report_seq", table_name="conversation_messages")
    op.drop_table("conversation_messages")
