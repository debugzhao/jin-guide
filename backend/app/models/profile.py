from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    province: Mapped[str] = mapped_column(String(50))
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # JSON list of subject strings e.g. ["物理", "化学"]
    subjects: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    batch: Mapped[str] = mapped_column(String(50), default="本科批")
    # Annual tuition budget in CNY
    family_budget: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # conservative / balanced / aggressive
    risk_style: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    completeness_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Preference(Base):
    __tablename__ = "preferences"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("student_profiles.id")
    )
    # JSON lists
    major_prefs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    city_prefs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    rejected_majors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    career_priority: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
