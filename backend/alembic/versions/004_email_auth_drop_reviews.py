"""Email auth + drop human_reviews

Revision ID: 004
Revises: 003
Create Date: 2026-07-01

Changes:
1. users: add email (unique), password_hash, email_verified
2. Drop human_reviews table (HITL feature removed)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: add email auth fields ─────────────────────────────────────────
    op.add_column("users", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(256), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── drop human_reviews (HITL removed) ────────────────────────────────────
    op.drop_index("ix_human_reviews_status_created", table_name="human_reviews")
    op.drop_table("human_reviews")


def downgrade() -> None:
    # Recreate human_reviews
    op.create_table(
        "human_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id", ondelete="SET NULL"), nullable=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("checklist_json", sa.JSON, nullable=True),
        sa.Column("conclusion", sa.String(50), nullable=True),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_human_reviews_status_created", "human_reviews", ["status", "created_at"])

    # Remove email auth columns
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
