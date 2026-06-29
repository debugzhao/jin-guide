from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("student_profiles.id"), nullable=True
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), nullable=True
    )
    # generating / completed / failed
    status: Mapped[str] = mapped_column(String(20), default="generating")
    # low / medium / high
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Structured plan with three tiers (conservative/balanced/aggressive)
    plan_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Evidence chain embedded directly (see PRD 6.5)
    evidence_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    dataset_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    # Soft delete support
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class VolunteerCheck(Base):
    __tablename__ = "volunteer_checks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("student_profiles.id"), nullable=True
    )
    report_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("reports.id"), nullable=True
    )
    # List of risk item objects
    risk_items_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # low / medium / high
    overall_risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # pending / completed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
