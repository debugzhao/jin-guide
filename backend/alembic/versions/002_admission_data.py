"""Add admission data tables: universities, admission_scores, rank_segments, subject_requirements

Revision ID: 002
Revises: 001
Create Date: 2026-06-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── universities ──────────────────────────────────────────────────────────
    op.create_table(
        "universities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(20), nullable=True),
        sa.Column("city", sa.String(50), nullable=True),
        sa.Column("province", sa.String(50), nullable=True),
        sa.Column("school_type", sa.String(50), nullable=True),
        sa.Column("is_985", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_211", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_shuangyiliu", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_medical_program", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("annual_tuition_min", sa.Integer, nullable=True),
        sa.Column("annual_tuition_max", sa.Integer, nullable=True),
    )
    op.create_index("ix_universities_name", "universities", ["name"])

    # ── admission_scores ──────────────────────────────────────────────────────
    op.create_table(
        "admission_scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("university_id", sa.String(36),
                  sa.ForeignKey("universities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("batch", sa.String(50), nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("major_category", sa.String(100), nullable=True),
        sa.Column("min_score", sa.Integer, nullable=True),
        sa.Column("min_rank", sa.Integer, nullable=True),
        sa.Column("avg_score", sa.Integer, nullable=True),
        sa.Column("avg_rank", sa.Integer, nullable=True),
        sa.Column("max_score", sa.Integer, nullable=True),
        sa.Column("enrollment_count", sa.Integer, nullable=True),
    )
    op.create_index("ix_admission_scores_lookup", "admission_scores",
                    ["province", "year", "batch", "subject_type"])
    op.create_index("ix_admission_scores_university", "admission_scores", ["university_id"])

    # ── rank_segments ─────────────────────────────────────────────────────────
    op.create_table(
        "rank_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("cumulative_rank", sa.Integer, nullable=False),
    )
    op.create_index("ix_rank_segments_lookup", "rank_segments",
                    ["province", "year", "subject_type", "score"], unique=True)

    # ── subject_requirements ─────────────────────────────────────────────────
    op.create_table(
        "subject_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("university_id", sa.String(36),
                  sa.ForeignKey("universities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("major_name", sa.String(200), nullable=False),
        sa.Column("required_subjects", sa.JSON, nullable=True),
        sa.Column("optional_subjects", sa.JSON, nullable=True),
        sa.Column("optional_required_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("restricted_subjects", sa.JSON, nullable=True),
        sa.Column("medical_restrictions", sa.JSON, nullable=True),
    )
    op.create_index("ix_subject_req_university", "subject_requirements", ["university_id"])
    op.create_index("ix_subject_req_major", "subject_requirements", ["university_id", "major_name"])


def downgrade() -> None:
    op.drop_table("subject_requirements")
    op.drop_table("rank_segments")
    op.drop_table("admission_scores")
    op.drop_table("universities")
