"""聊天会话 + 调试摘要

Revision ID: 005
Revises: 004
Create Date: 2026-07-01

变更：
1. 新增表：report_conversations —— 存储每份报告的问答历史（最多 50 条消息）
2. agent_runs：新增 debug_summary_json（JSONB）列，用于存放运行结束后的调试遥测数据
3. agent_runs：新增 duration_seconds（Float）列，方便快速查询耗时
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── report_conversations ────────────────────────────────────────────────────
    op.create_table(
        "report_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "report_id",
            sa.String(36),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # {role, content, citations, created_at} 组成的 JSONB 列表——应用层负责限制最多 50 条消息
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
        "ix_report_conversations_report_id", "report_conversations", ["report_id"]
    )
    op.create_index(
        "ix_report_conversations_user_id", "report_conversations", ["user_id"]
    )

    # ── agent_runs 新增列 ────────────────────────────────────────────────────
    op.add_column(
        "agent_runs",
        sa.Column(
            "debug_summary_json",
            postgresql.JSONB,
            nullable=True,
            comment="由 Worker 在运行结束后写入的聚合调试遥测数据",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "duration_seconds",
            sa.Float,
            nullable=True,
            comment="运行的墙钟耗时（秒）",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "duration_seconds")
    op.drop_column("agent_runs", "debug_summary_json")
    op.drop_index("ix_report_conversations_user_id", table_name="report_conversations")
    op.drop_index(
        "ix_report_conversations_report_id", table_name="report_conversations"
    )
    op.drop_table("report_conversations")


2
