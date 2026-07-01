from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # Unique thread ID used by LangGraph checkpoint system
    thread_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("student_profiles.id"), nullable=True
    )
    # generate_report / check_volunteer
    task_type: Mapped[str] = mapped_column(String(50))
    # queued / running / interrupted / completed / failed / timeout
    status: Mapped[str] = mapped_column(String(20), default="queued")
    cost_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    trace_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Aggregated debug telemetry: {node_timings, tool_call_summary, state_summary, cost_breakdown}
    debug_summary_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Wall-clock duration in seconds, written at completion
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
