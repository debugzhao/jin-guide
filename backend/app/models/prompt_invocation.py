from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PromptInvocation(Base):
    """仅记录 Prompt 版本和调用状态，不保存用户原文或动态上下文。"""

    __tablename__ = "observability_prompt_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    prompt_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    model_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    context_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
