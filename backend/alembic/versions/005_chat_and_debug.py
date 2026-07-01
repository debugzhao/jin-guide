"""Chat conversations + debug summary

Revision ID: 005
Revises: 004
Create Date: 2026-07-01

Changes:
1. New table: report_conversations — stores per-report chat history (max 50 messages)
2. agent_runs: add debug_summary_json JSONB column for post-run debug telemetry
3. agent_runs: add duration_seconds Float for quick latency queries
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
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        # JSONB list of {role, content, citations, created_at} — capped at 50 messages in app layer
        sa.Column("messages_json", postgresql.JSONB, server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_report_conversations_report_id", "report_conversations", ["report_id"])
    op.create_index("ix_report_conversations_user_id", "report_conversations", ["user_id"])

    # ── agent_runs additions ────────────────────────────────────────────────────
    op.add_column(
        "agent_runs",
        sa.Column("debug_summary_json", postgresql.JSONB, nullable=True, comment="Aggregated debug telemetry written by Worker after run completes"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("duration_seconds", sa.Float, nullable=True, comment="Wall-clock run duration in seconds"),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "duration_seconds")
    op.drop_column("agent_runs", "debug_summary_json")
    op.drop_index("ix_report_conversations_user_id", table_name="report_conversations")
    op.drop_index("ix_report_conversations_report_id", table_name="report_conversations")
    op.drop_table("report_conversations")
