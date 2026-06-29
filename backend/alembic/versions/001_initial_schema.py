"""Initial schema for 问津 Agent M1

Revision ID: 001
Revises:
Create Date: 2026-06-29

Creates all core tables:
- users, sessions
- student_profiles, preferences
- agent_runs
- reports, volunteer_checks
- human_reviews
- documents, chunks
- province_thresholds (new in v0.9)

Indexes follow PRD Section 6.2 key index strategy.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (placeholder; embedding stored as Text in M1)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("openid", sa.String(128), unique=True, nullable=True),
        sa.Column("phone", sa.String(20), unique=True, nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── sessions ────────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("anonymous_id", sa.String(36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # ── student_profiles ────────────────────────────────────────────────────
    op.create_table(
        "student_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("score", sa.Integer, nullable=True),
        sa.Column("rank", sa.Integer, nullable=True),
        sa.Column("subjects", sa.JSON, nullable=True),
        sa.Column("batch", sa.String(50), nullable=False, server_default="本科批"),
        sa.Column("family_budget", sa.Integer, nullable=True),
        sa.Column("risk_style", sa.String(20), nullable=True),
        sa.Column(
            "completeness_score",
            sa.Float,
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_student_profiles_user_id", "student_profiles", ["user_id"])

    # ── preferences ─────────────────────────────────────────────────────────
    op.create_table(
        "preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("student_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("major_prefs", sa.JSON, nullable=True),
        sa.Column("city_prefs", sa.JSON, nullable=True),
        sa.Column("rejected_majors", sa.JSON, nullable=True),
        sa.Column("career_priority", sa.String(100), nullable=True),
    )
    op.create_index("ix_preferences_profile_id", "preferences", ["profile_id"])

    # ── agent_runs ──────────────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("thread_id", sa.String(36), unique=True, nullable=False),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("student_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # generate_report / check_volunteer
        sa.Column("task_type", sa.String(50), nullable=False),
        # queued / running / interrupted / completed / failed / timeout
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("cost_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("trace_url", sa.String(500), nullable=True),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # PRD 6.2: composite index for user run history queries and rate limiting
    op.create_index(
        "ix_agent_runs_user_status_created",
        "agent_runs",
        ["user_id", "status", "created_at"],
    )

    # ── reports ─────────────────────────────────────────────────────────────
    op.create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("student_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # generating / completed / failed
        sa.Column("status", sa.String(20), nullable=False, server_default="generating"),
        # low / medium / high
        sa.Column("risk_level", sa.String(20), nullable=True),
        sa.Column("risk_score", sa.Float, nullable=True),
        # Structured three-tier plan (see PRD 6.4)
        sa.Column("plan_json", sa.JSON, nullable=True),
        # Evidence chain embedded (see PRD 6.5)
        sa.Column("evidence_json", sa.JSON, nullable=True),
        sa.Column("dataset_version", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reports_profile_id", "reports", ["profile_id"])
    op.create_index("ix_reports_run_id", "reports", ["run_id"])
    op.create_index("ix_reports_created_at", "reports", ["created_at"])

    # ── volunteer_checks ────────────────────────────────────────────────────
    op.create_table(
        "volunteer_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("student_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "report_id",
            sa.String(36),
            sa.ForeignKey("reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("risk_items_json", sa.JSON, nullable=True),
        sa.Column("overall_risk_level", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── human_reviews ────────────────────────────────────────────────────────
    op.create_table(
        "human_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "report_id",
            sa.String(36),
            sa.ForeignKey("reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewer_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # pending / in_review / need_more_info / reviewed / closed / timeout
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        # Checklist JSON (see PRD 11.5)
        sa.Column("checklist_json", sa.JSON, nullable=True),
        # approved / rejected / need_more_info
        sa.Column("conclusion", sa.String(50), nullable=True),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # SLA timeout = created_at + 4h (see PRD 11.2, 13.3)
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
    )
    # PRD 6.2: composite index for pending review queue ordering
    op.create_index(
        "ix_human_reviews_status_created",
        "human_reviews",
        ["status", "created_at"],
    )

    # ── documents ───────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        # admission_plan / admission_score / rank_segment / charter / major_intro / employment_report / policy
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        # official / semi-official / third-party / internal
        sa.Column("authority_level", sa.String(30), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        # raw / parsed / verified / published / deprecated
        sa.Column("status", sa.String(20), nullable=False, server_default="raw"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_year", "documents", ["year"])

    # ── chunks ──────────────────────────────────────────────────────────────
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        # Stored as Text for M1; M2 will use pgvector vector(1536) type
        sa.Column("embedding", sa.Text, nullable=True),
        # Model identifier for migration filtering (see PRD 9.2)
        sa.Column("embedding_model", sa.String(100), nullable=True),
        # Metadata: province, year, university_id, etc.
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    # ── province_thresholds ──────────────────────────────────────────────────
    # New in PRD v0.9: replaces hardcoded tier thresholds
    op.create_table(
        "province_thresholds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        # high_rush: rank gap > this value (e.g. 5000)
        sa.Column("high_rush_rank_gap", sa.Integer, nullable=False, server_default="5000"),
        # rush: rank gap in [rush_rank_gap_min, rush_rank_gap_max]
        sa.Column("rush_rank_gap_min", sa.Integer, nullable=False, server_default="1000"),
        sa.Column("rush_rank_gap_max", sa.Integer, nullable=False, server_default="5000"),
        # target: rank gap within ±target_rank_gap
        sa.Column("target_rank_gap", sa.Integer, nullable=False, server_default="1000"),
        # safe: rank gap > safe_rank_gap (student rank safely below history avg)
        sa.Column("safe_rank_gap", sa.Integer, nullable=False, server_default="2000"),
    )
    op.create_index(
        "ix_province_thresholds_province_year",
        "province_thresholds",
        ["province", "year"],
        unique=True,
    )

    # Seed default thresholds for 河南/山东 (PRD 8.1.2)
    op.execute("""
        INSERT INTO province_thresholds
            (id, province, year, high_rush_rank_gap, rush_rank_gap_min, rush_rank_gap_max, target_rank_gap, safe_rank_gap)
        VALUES
            ('thresh_henan_2026', '河南', 2026, 5000, 1000, 5000, 1000, 2000),
            ('thresh_shandong_2026', '山东', 2026, 5000, 1000, 5000, 1000, 2000)
    """)


def downgrade() -> None:
    op.drop_table("province_thresholds")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("human_reviews")
    op.drop_table("volunteer_checks")
    op.drop_table("reports")
    op.drop_table("agent_runs")
    op.drop_table("preferences")
    op.drop_table("student_profiles")
    op.drop_table("sessions")
    op.drop_table("users")
