from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

_MAX_MESSAGES = 50


class ReportConversation(Base):
    """
    Stores the chat history between a user and ConversationAgent for a given report.
    messages_json is a list of {role, content, citations, created_at} dicts.
    Capped at _MAX_MESSAGES in the application layer before writing.
    """

    __tablename__ = "report_conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    report_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # List of message dicts: {role: "user"|"assistant", content: str, citations: [...], created_at: ISO}
    messages_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class IntakeConversation(Base):
    """
    建档前 Chat-first 聊天历史（IntakeAgent）冷层兜底存储。

    这里还没有 report_id 可以挂靠（建档表单甚至可能还没触发），所以不能像
    ReportConversation 一样按 report_id 分表；owner_key 是登录用户的 user_id
    或匿名会话的 anonymous_id 二选一，本身不再是唯一约束——同一个人可以有
    多条会话（多会话历史，`id` 即会话/thread id），列表按 owner_key 查询、
    按 updated_at 倒序展示，见 `docs/backend-prd-v2.md` §5.6b。
    """

    __tablename__ = "intake_conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # 登录用户是 user_id（36 位 uuid），匿名会话是 "anon:" + 36 位 uuid（41 字符）
    owner_key: Mapped[str] = mapped_column(String(48), nullable=False)
    # 首条用户消息截断生成，供侧栏会话列表展示；None 表示尚未产生过消息
    title: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    messages_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    # 软删除（对齐 reports/documents 表的约定，见 backend/docs/03_data_model.md §4）
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
