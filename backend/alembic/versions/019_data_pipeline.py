"""Add traceable admission-data pipeline tables.

Revision ID: 019_data_pipeline
Revises: 018_prompt_invocations
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "019_data_pipeline"
down_revision: Union[str, None] = "018_prompt_invocations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("entry_url", sa.String(1000), nullable=False),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("target_university_code", sa.String(20), nullable=True),
        sa.Column("collection_method", sa.String(30), nullable=False),
        sa.Column("parser", sa.String(100), nullable=False),
        sa.Column("update_frequency", sa.String(50), nullable=False),
        sa.Column("authority_level", sa.String(30), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checksum", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_data_sources_type_year", "data_sources", ["data_type", "year"])

    op.create_table(
        "collection_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parsed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("valid_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_collection_runs_source_started", "collection_runs", ["source_id", "started_at"])

    op.create_table(
        "source_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(100), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("collection_run_id", sa.String(36), sa.ForeignKey("collection_runs.id"), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("source_id", "checksum", name="uq_source_documents_source_checksum"),
    )
    op.create_index("ix_source_documents_checksum", "source_documents", ["checksum"])

    op.add_column(
        "documents",
        sa.Column(
            "source_document_id",
            sa.String(36),
            sa.ForeignKey("source_documents.id"),
            nullable=True,
        ),
    )
    op.add_column("documents", sa.Column("raw_storage_path", sa.String(1000), nullable=True))
    op.create_unique_constraint(
        "uq_documents_source_document_id", "documents", ["source_document_id"]
    )

    op.create_table(
        "staging_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_document_id", sa.String(36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("collection_run_id", sa.String(36), sa.ForeignKey("collection_runs.id"), nullable=False),
        sa.Column("record_type", sa.String(80), nullable=False),
        sa.Column("natural_key", sa.String(64), nullable=False),
        sa.Column("review_status", sa.String(30), nullable=False),
        sa.Column("payload_json", postgresql.JSONB, nullable=False),
        sa.Column("issues_json", postgresql.JSONB, nullable=True),
        sa.Column("reviewed_by", sa.String(100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("source_document_id", "natural_key", name="uq_staging_document_natural_key"),
    )
    op.create_index("ix_staging_records_review_status", "staging_records", ["review_status"])
    op.create_index("ix_staging_records_run", "staging_records", ["collection_run_id"])

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False, unique=True),
        sa.Column("dataset_type", sa.String(50), nullable=False),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("manifest_json", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("dataset_type", "province", "year", "version", name="uq_dataset_version_scope"),
    )
    op.create_index("ix_dataset_versions_lookup", "dataset_versions", ["dataset_type", "province", "year", "status"])

    op.create_table(
        "published_data_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_version_id", sa.String(36), sa.ForeignKey("dataset_versions.id"), nullable=False),
        sa.Column("record_type", sa.String(80), nullable=False),
        sa.Column("natural_key", sa.String(64), nullable=False),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=True),
        sa.Column("batch", sa.String(50), nullable=True),
        sa.Column("university_code", sa.String(20), nullable=True),
        sa.Column("major_group_code", sa.String(50), nullable=True),
        sa.Column("major_code", sa.String(50), nullable=True),
        sa.Column("payload_json", postgresql.JSONB, nullable=False),
        sa.Column("provenance_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("dataset_version_id", "natural_key", name="uq_published_dataset_natural_key"),
    )
    op.create_index("ix_published_records_lookup", "published_data_records", ["province", "year", "record_type", "subject_type", "batch"])
    op.create_index("ix_published_records_university", "published_data_records", ["university_code", "major_group_code"])


def downgrade() -> None:
    op.drop_constraint("uq_documents_source_document_id", "documents", type_="unique")
    op.drop_column("documents", "raw_storage_path")
    op.drop_column("documents", "source_document_id")
    op.drop_table("published_data_records")
    op.drop_table("dataset_versions")
    op.drop_table("staging_records")
    op.drop_table("source_documents")
    op.drop_table("collection_runs")
    op.drop_table("data_sources")
