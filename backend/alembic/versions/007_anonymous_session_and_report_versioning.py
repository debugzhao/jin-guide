"""Anonymous session support, report versioning, notifications, data model scaffolding

Revision ID: 007
Revises: 006
Create Date: 2026-07-09

Changes (docs/backend-prd-v2.md §6.1):
1. reports: add user_id, anonymous_id, version (default 1), parent_report_id
   (self-referential, for /refine version lineage), run_summary_json (JSONB)
2. student_profiles: add anonymous_id (匿名建档草稿归属)
3. agent_runs: add anonymous_id (让匿名 run 产出的 report 能被正确归属)
4. New table: admission_plans (招生计划，区别于 admission_scores 历年投档线)
5. New table: rule_requirements (通用规则+来源引用存储)
6. New table: notifications (站内通知)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── reports: versioning + ownership ─────────────────────────────────────────
    op.add_column("reports", sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("reports", sa.Column("anonymous_id", sa.String(36), nullable=True))
    op.add_column("reports", sa.Column("version", sa.Integer, nullable=False, server_default="1"))
    op.add_column(
        "reports",
        sa.Column("parent_report_id", sa.String(36), sa.ForeignKey("reports.id"), nullable=True),
    )
    op.add_column("reports", sa.Column("run_summary_json", postgresql.JSONB, nullable=True))
    op.create_index("ix_reports_user_id", "reports", ["user_id"])
    op.create_index("ix_reports_anonymous_id", "reports", ["anonymous_id"])
    op.create_index("ix_reports_parent_report_id", "reports", ["parent_report_id"])

    # ── student_profiles: anonymous draft ownership ─────────────────────────────
    op.add_column("student_profiles", sa.Column("anonymous_id", sa.String(36), nullable=True))
    op.create_index("ix_student_profiles_anonymous_id", "student_profiles", ["anonymous_id"])

    # ── agent_runs: anonymous ownership (so the Report it produces can be stamped) ──
    op.add_column("agent_runs", sa.Column("anonymous_id", sa.String(36), nullable=True))
    op.create_index("ix_agent_runs_anonymous_id", "agent_runs", ["anonymous_id"])

    # ── admission_plans ──────────────────────────────────────────────────────────
    op.create_table(
        "admission_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("batch", sa.String(50), nullable=False),
        sa.Column(
            "university_id", sa.String(36), sa.ForeignKey("universities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("major_group", sa.String(100), nullable=True),
        sa.Column("major_code", sa.String(50), nullable=True),
        sa.Column("quota", sa.Integer, nullable=True),
        sa.Column("subjects", sa.JSON, nullable=True),
        sa.Column("tuition", sa.Integer, nullable=True),
        sa.Column("dataset_version", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_admission_plans_lookup", "admission_plans", ["province", "year", "batch", "major_group"]
    )

    # ── rule_requirements ────────────────────────────────────────────────────────
    op.create_table(
        "rule_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("province", sa.String(50), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column("rule_json", postgresql.JSONB, nullable=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_rule_requirements_target", "rule_requirements", ["target_id"])

    # ── notifications ────────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("payload_json", postgresql.JSONB, nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("rule_requirements")
    op.drop_table("admission_plans")
    op.drop_index("ix_agent_runs_anonymous_id", table_name="agent_runs")
    op.drop_column("agent_runs", "anonymous_id")
    op.drop_index("ix_student_profiles_anonymous_id", table_name="student_profiles")
    op.drop_column("student_profiles", "anonymous_id")
    op.drop_index("ix_reports_parent_report_id", table_name="reports")
    op.drop_index("ix_reports_anonymous_id", table_name="reports")
    op.drop_index("ix_reports_user_id", table_name="reports")
    op.drop_column("reports", "run_summary_json")
    op.drop_column("reports", "parent_report_id")
    op.drop_column("reports", "version")
    op.drop_column("reports", "anonymous_id")
    op.drop_column("reports", "user_id")
