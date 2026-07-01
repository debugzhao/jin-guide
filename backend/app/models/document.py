from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

EMBEDDING_DIMS = 1536


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # admission_plan / admission_score / rank_segment / charter / major_intro / employment_report / policy
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    year: Mapped[Optional[int]] = mapped_column(nullable=True)
    # official / semi-official / third-party / internal
    authority_level: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # SHA256 checksum of file content for dedup
    checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # raw / parsed / verified / published / deprecated
    status: Mapped[str] = mapped_column(String(20), default="raw")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    # Soft delete
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id")
    )
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Optional[list]] = mapped_column(Vector(EMBEDDING_DIMS), nullable=True)
    # Model identifier used to generate embedding (for migration filtering)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Metadata: province, year, university_id, major_id, page_num, etc.
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
