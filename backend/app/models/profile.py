from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# docs/memory-architecture.md 第六节 P4 第 1 步：来源/置信度/状态/取代链，
# StudentProfile 和 Preference 共用同一套字段，混入一个 mixin 避免重复声明。
class _ProvenanceMixin:
    # user_explicit：用户表单/聊天里明确填写或表达；model_inferred：AI 从对话推断
    # （目前唯一写入路径是表单提交，恒为 user_explicit；model_inferred 是给未来
    # Chat 提取链路预留的取值，本次迁移只加字段不接提取逻辑）
    source_type: Mapped[str] = mapped_column(String(20), default="user_explicit")
    # 仅 model_inferred 记录有意义，user_explicit 恒为 None
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # confirmed / proposed / rejected / superseded，见 docs/memory-architecture.md §5.4
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    last_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 来源于某条对话消息时指向 conversation_messages.id；表单提交场景恒为 None
    source_message_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("memory_conversation_messages.id", ondelete="SET NULL"), nullable=True
    )
    # 自引用：这条记录被哪条新记录取代、何时取代——同一偏好改过多次时保留历史链条，
    # 不直接覆盖旧值
    superseded_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    superseded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudentProfile(_ProvenanceMixin, Base):
    __tablename__ = "candidate_student_profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("auth_users.id"), nullable=True
    )
    # 匿名建档阶段草稿归属；登录/注册后绑定到 user_id（见 auth.py 的绑定逻辑）
    anonymous_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    province: Mapped[str] = mapped_column(String(50))
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 选科字符串组成的 JSON 列表，例如 ["物理", "化学"]
    subjects: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    batch: Mapped[str] = mapped_column(String(50), default="本科批")
    # 年度学费预算（人民币）
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
    __table_args__ = (
        ForeignKeyConstraint(
            ["superseded_by"],
            ["candidate_student_profiles.id"],
            ondelete="SET NULL",
            name="fk_candidate_student_profiles_superseded_by",
        ),
    )


class Preference(_ProvenanceMixin, Base):
    __tablename__ = "candidate_preferences"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("candidate_student_profiles.id")
    )
    # JSON 数组
    major_prefs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    city_prefs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    rejected_majors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    career_priority: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["superseded_by"],
            ["candidate_preferences.id"],
            ondelete="SET NULL",
            name="fk_candidate_preferences_superseded_by",
        ),
    )
