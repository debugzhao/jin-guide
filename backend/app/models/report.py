from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
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
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    # 匿名建档阶段生成的报告归属；登录/注册后绑定到 user_id（见 auth.py 的绑定逻辑）
    anonymous_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # unique：一个 run_id 只对应一份权威 Report 行（reflection 重试循环内的多次
    # report 节点执行按 run_id upsert 同一行，不再每次 uuid4() 插入新行）
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), nullable=True, unique=True
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
    # 同一血缘链内从 1 递增；/refine 产出的新版本 parent_report_id 指向被 refine 的报告
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_report_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("reports.id"), nullable=True
    )
    # 用户可见的生成过程摘要，供报告页"决策过程回放"卡片使用（只读回放，不重新调用 Agent）
    run_summary_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
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
