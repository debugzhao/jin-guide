from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class HumanReview(Base):
    __tablename__ = "human_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    report_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("reports.id"), nullable=True
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), nullable=True
    )
    reviewer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    # pending / in_review / need_more_info / reviewed / closed / timeout
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Checklist structure (see PRD 11.5 for schema)
    checklist_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # approved / rejected / need_more_info
    conclusion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # SLA deadline: created_at + 4h; scanned by timeout job
    timeout_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
