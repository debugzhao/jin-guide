"""add prompt invocation audit table

Revision ID: 018_prompt_invocations
Revises: 017
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "018_prompt_invocations"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("prompt_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("prompt_hash", sa.String(length=80), nullable=False),
        sa.Column("model_alias", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=100), nullable=True),
        sa.Column("context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_invocations_prompt_name", "prompt_invocations", ["prompt_name"])
    op.create_index("ix_prompt_invocations_status", "prompt_invocations", ["status"])
    op.create_index("ix_prompt_invocations_created_at", "prompt_invocations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_prompt_invocations_created_at", table_name="prompt_invocations")
    op.drop_index("ix_prompt_invocations_status", table_name="prompt_invocations")
    op.drop_index("ix_prompt_invocations_prompt_name", table_name="prompt_invocations")
    op.drop_table("prompt_invocations")
