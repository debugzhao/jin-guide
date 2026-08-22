from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class DataSource(Base):
    __tablename__ = "pipeline_data_sources"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entry_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_university_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    collection_method: Mapped[str] = mapped_column(String(30), nullable=False)
    parser: Mapped[str] = mapped_column(String(100), nullable=False)
    update_frequency: Mapped[str] = mapped_column(String(50), nullable=False)
    authority_level: Mapped[str] = mapped_column(String(30), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_pipeline_data_sources_type_year", "data_type", "year"),
    )


class CollectionRun(Base):
    __tablename__ = "pipeline_collection_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("pipeline_data_sources.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_pipeline_collection_runs_source_started", "source_id", "started_at"),)


class SourceDocument(Base):
    __tablename__ = "pipeline_source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("pipeline_data_sources.id"), nullable=False
    )
    collection_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_collection_runs.id"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="raw")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("source_id", "checksum", name="uq_pipeline_source_documents_source_checksum"),
        Index("ix_pipeline_source_documents_checksum", "checksum"),
    )


class StagingRecord(Base):
    __tablename__ = "pipeline_staging_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_source_documents.id"), nullable=False
    )
    collection_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_collection_runs.id"), nullable=False
    )
    record_type: Mapped[str] = mapped_column(String(80), nullable=False)
    natural_key: Mapped[str] = mapped_column(String(64), nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    issues_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint(
            "source_document_id", "natural_key", name="uq_pipeline_staging_document_natural_key"
        ),
        Index("ix_pipeline_staging_records_review_status", "review_status"),
        Index("ix_pipeline_staging_records_run", "collection_run_id"),
    )


class DatasetVersion(Base):
    __tablename__ = "pipeline_dataset_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    dataset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    province: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manifest_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "dataset_type", "province", "year", "version", name="uq_pipeline_dataset_version_scope"
        ),
        Index("ix_pipeline_dataset_versions_lookup", "dataset_type", "province", "year", "status"),
    )


class PublishedDataRecord(Base):
    __tablename__ = "pipeline_published_data_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_dataset_versions.id"), nullable=False
    )
    record_type: Mapped[str] = mapped_column(String(80), nullable=False)
    natural_key: Mapped[str] = mapped_column(String(64), nullable=False)
    province: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    batch: Mapped[str | None] = mapped_column(String(50), nullable=True)
    university_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    major_group_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    major_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "natural_key", name="uq_pipeline_published_dataset_natural_key"
        ),
        Index(
            "ix_pipeline_published_records_lookup",
            "province", "year", "record_type", "subject_type", "batch",
        ),
        Index("ix_pipeline_published_records_university", "university_code", "major_group_code"),
    )
