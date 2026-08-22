from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReportConversation(Base):
    """
    Parent row for the chat history between a user and ConversationAgent for a
    given report. Message content itself lives in ConversationMessage rows
    (see below) — this row only tracks conversation identity/ownership and
    `updated_at`. Used to hold `messages_json` directly until the P2
    append-only migration (docs/memory-architecture.md §六 P2) cut reads/writes
    over to ConversationMessage and dropped that column.
    """

    __tablename__ = "memory_report_conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    report_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs_reports.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    # 匿名会话标识（登录用户为 null）；避免所有匿名用户共享 user_id IS NULL 导致
    # 同一份报告下不同匿名人互相读到对方的问答历史
    anonymous_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(default=0, nullable=False)
    # 乐观锁：并发的 get_or_create_conversation_row 调用可能同时 SELECT 到同一行，
    # version 不匹配时 SQLAlchemy 拒绝提交（StaleDataError），调用方据此重试。必须
    # 在 version 列定义*之后*声明，__mapper_args__ 在类体执行到这一行时才能引用到
    # 上面绑定的列对象。
    __mapper_args__ = {"version_id_col": version}
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

    __tablename__ = "memory_intake_conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # 登录用户是 user_id（36 位 uuid），匿名会话是 "anon:" + 36 位 uuid（41 字符）
    owner_key: Mapped[str] = mapped_column(String(48), nullable=False)
    # 首条用户消息截断生成，供侧栏会话列表展示；None 表示尚未产生过消息
    title: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(default=0, nullable=False)
    # 乐观锁，理由同 ReportConversation；同样必须放在 version 列定义之后
    __mapper_args__ = {"version_id_col": version}
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


class ConversationMessage(Base):
    """
    单条消息独立一行的追加式存储，替代 ReportConversation/IntakeConversation.messages_json
    整块 JSONB 数组（见 docs/memory-architecture.md 第六节 P2）。report_conversation_id 和
    intake_conversation_id 二选一（CHECK 约束保证恰好一个非空），seq 是同一会话内的递增序号。
    追加新消息只 INSERT 新行，不再需要"读整个数组 → 改 → 整体写回"，天然避免并发覆盖丢消息
    ——两个并发请求最多在 seq 唯一约束上冲突，冲突方重新计算 seq 重试即可，不会像旧的整体
    覆盖写那样丢失对方已经写入的消息内容。
    """

    __tablename__ = "memory_conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    report_conversation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("memory_report_conversations.id", ondelete="CASCADE"), nullable=True
    )
    intake_conversation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("memory_intake_conversations.id", ondelete="CASCADE"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 仅 ReportConversation 侧消息使用；IntakeConversation 侧消息恒为 None
    citations: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        CheckConstraint(
            "(report_conversation_id IS NULL) != (intake_conversation_id IS NULL)",
            name="ck_memory_conversation_messages_exactly_one_parent",
        ),
        # Postgres 里 NULL 在唯一约束中互不冲突，所以这两个约束分别只对"属于该类型
        # 会话的消息"生效，不会因为另一类型的行 parent_id 恒为 NULL 而误判冲突。
        UniqueConstraint("report_conversation_id", "seq", name="uq_memory_conversation_messages_report_seq"),
        UniqueConstraint("intake_conversation_id", "seq", name="uq_memory_conversation_messages_intake_seq"),
        Index("ix_memory_conversation_messages_report_seq", "report_conversation_id", "seq"),
        Index("ix_memory_conversation_messages_intake_seq", "intake_conversation_id", "seq"),
    )


class ConversationSummary(Base):
    """
    结构化增量摘要（见 docs/memory-architecture.md 第六节 P2/5.2）：不是自然语言摘要，而是
    confirmed_facts/preferences/rejected_options/previous_decisions/open_questions 的结构化
    JSON，覆盖已经滑出 Agent 最近消息窗口的历史，随对话增长做增量更新，而不是每次从头重新
    总结全部历史。摘要不是事实源，必须携带来源模型、Prompt 版本、覆盖范围和生成状态，出问题
    时可追溯；生成失败时保留上一次成功的摘要不变，不阻断聊天（Agent 侧退回到只用最近消息窗口，
    等同于当前未接入摘要时的行为）。
    """

    __tablename__ = "memory_conversation_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    report_conversation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("memory_report_conversations.id", ondelete="CASCADE"), nullable=True
    )
    intake_conversation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("memory_intake_conversations.id", ondelete="CASCADE"), nullable=True
    )
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 本次摘要覆盖到哪条消息的 seq（含）；Agent 侧只需再拼上 seq > covered_through_seq
    # 的最近原文消息，两者拼接起来就是"早期事实 + 最新语境"的完整上下文
    covered_through_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_model: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    tokens_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # ready / failed —— failed 表示最近一次生成尝试失败，summary_json 仍是上一次成功的内容
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        CheckConstraint(
            "(report_conversation_id IS NULL) != (intake_conversation_id IS NULL)",
            name="ck_memory_conversation_summaries_exactly_one_parent",
        ),
        # 每个会话至多一条摘要行（NULL 在唯一约束中互不冲突，两条约束各自只约束
        # 自己类型的会话）
        UniqueConstraint("report_conversation_id", name="uq_memory_conversation_summaries_report"),
        UniqueConstraint("intake_conversation_id", name="uq_memory_conversation_summaries_intake"),
    )
