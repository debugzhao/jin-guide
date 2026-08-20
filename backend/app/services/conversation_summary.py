"""
结构化增量对话摘要 —— 见 docs/memory-architecture.md §六 P2。

Agent 每次只能看到最近 MAX_HISTORY_MESSAGES 条原始消息（ConversationAgent
是 10 条，IntakeAgent 是 16 条）。一旦对话轮数超过这个窗口，更早的对话轮次
就再也不会进入 prompt —— 没有任何机制记录它们。本模块维护一份结构化 JSON
摘要（confirmed_facts / preferences / rejected_options / previous_decisions /
open_questions），专门覆盖那些已经滑出窗口的历史消息，这样像"预算 5 万"这类
事实，即使说出它的那轮对话早已被滚出窗口，依然能持续留在 Agent 视野里。

摘要不是权威数据源 —— ConversationMessage 表才是 —— 所以每次重新生成都会
记录使用的模型、Prompt 版本、以及覆盖的消息范围（见 ConversationSummary）。
生成过程是 best-effort 的（与 intake_chat.py 里标题升级同一可靠性级别，同样
通过 FastAPI BackgroundTasks 触发）：失败时保留上一份摘要不变，且无论摘要
是否存在，调用方始终还能兜底用原始的近期消息窗口。
"""
from __future__ import annotations

import json

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.conversation import ConversationMessage
from app.prompts import prompt_registry
from app.prompts.tracing import track_prompt_invocation
from app.services import conversation_store as store

logger = structlog.get_logger()

_PROMPT = prompt_registry.get("conversation_summary")
_SUMMARY_MODEL = _PROMPT.model.alias
_PROMPT_VERSION = _PROMPT.version
_SUMMARY_KEYS = (
    "confirmed_facts",
    "preferences",
    "rejected_options",
    "previous_decisions",
    "open_questions",
)


class ConversationSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_facts: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    rejected_options: list[str] = Field(default_factory=list)
    previous_decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_list_fields(cls, value):
        return _normalize_summary_field(value)


def _build_summary_prompt(previous_summary: dict | None, segment_messages: list[ConversationMessage]) -> str:
    segment_text = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}：{m.content}" for m in segment_messages
    )
    previous_text = (
        json.dumps(previous_summary, ensure_ascii=False) if previous_summary else "（还没有历史摘要）"
    )
    return _PROMPT.render(
        "user",
        previous_summary=previous_text,
        conversation_segment=segment_text,
    )


async def _call_summary_llm(
    prompt: str, *, parent_kind: str | None = None, parent_id: str | None = None
) -> str:
    """
    这里必须走流式请求，不能像 report_agent.py 那样一次性等完整响应：结构化
    摘要这类任务 kimi-k2.6 的 reasoning_content 经常很长，实测非流式请求哪怕
    给 240s 超时也稳定触发 httpx.ReadTimeout（httpx 对一次性大响应体的读取
    有整体超时窗口）。conversation_agent.py/intake_agent.py 两个已经跑通的
    聊天链路都是靠流式请求把"總等待时间"拆成很多次小间隔的 chunk 读取来规避
    这个限制，这里复用同一套做法，只是不逐 token yield，而是攒满后一次性
    返回给调用方解析。
    """
    full_content = ""
    context = {"parent_kind": parent_kind}
    if parent_kind == "report":
        context["report_id"] = parent_id
    elif parent_kind == "intake":
        context["conversation_id"] = parent_id
    async with track_prompt_invocation(_PROMPT, **context) as invocation:
        async with httpx.AsyncClient(timeout=_PROMPT.model.timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{settings.litellm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.litellm_master_key}",
                    "Content-Type": "application/json",
                },
                json={
                    **invocation.request_options(),
                    "messages": [{"role": "user", "content": prompt}],
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        delta = chunk["choices"][0]["delta"]
                        full_content += delta.get("content") or ""
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
    return full_content.strip()


def _parse_summary_response(content: str) -> dict | None:
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # kimi-k2.6 有时会在 JSON 前后夹带解释性文字（尽管 Prompt 明确要求不要），
    # 用最外层花括号兜底提取，而不是要求整段输出必须是纯 JSON。
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    try:
        return ConversationSummaryOutput.model_validate(parsed).model_dump()
    except Exception:
        return None


def _normalize_summary_field(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, dict):
        return [f"{k}：{v}" for k, v in value.items() if v]
    if value:
        return [str(value)]
    return []


# ConversationMessage 侧的列映射，特意留在本模块内——ConversationSummary
# 自己对应的列是在 conversation_store.py 的 load_summary/upsert_summary 里
# 根据同一个 `parent_kind` 字符串单独解析的，所以两个模型的列永远不会用混
# （具体要避免的 bug 见 conversation_store._MESSAGE_PARENT_COLUMNS 上的
# 注释：把一个模型的列传进针对另一个模型的查询，不会报错，只会悄悄产生
# 一次 cross join）。
_MESSAGE_PARENT_COLUMNS = {
    "report": ConversationMessage.report_conversation_id,
    "intake": ConversationMessage.intake_conversation_id,
}


async def maybe_generate_summary(
    parent_kind: str,
    parent_id: str,
    *,
    window_size: int,
) -> None:
    """
    best-effort 的后台任务（FastAPI BackgroundTasks —— 与 intake_chat.py 的
    _maybe_upgrade_title 同一可靠性级别）：检查上次摘要更新之后，是否已经
    有整整一个窗口的消息滑出了近期窗口，如果是就重新生成覆盖这部分消息的
    结构化摘要。

    `parent_kind` 取值 "report" 或 "intake"；`window_size` 应该与对应 Agent
    的 MAX_HISTORY_MESSAGES 保持一致，这样摘要覆盖范围正好从原始近期消息
    窗口结束的地方接上，不留缝隙也不重叠。
    """
    from app.database import async_session_maker

    parent_column = _MESSAGE_PARENT_COLUMNS[parent_kind]
    async with async_session_maker() as db:
        try:
            latest_seq = await _load_latest_seq(db, parent_column, parent_id)
            existing = await store.load_summary(db, parent_kind=parent_kind, parent_id=parent_id)
            covered_through_seq = existing.covered_through_seq if existing else 0

            if latest_seq - covered_through_seq < window_size:
                # 还没攒够一整个窗口的新老化消息，暂不需要重新生成摘要
                return

            target_covered_seq = latest_seq - window_size
            segment_messages = await _load_segment(
                db, parent_column, parent_id, covered_through_seq, target_covered_seq
            )
            if not segment_messages:
                return

            prompt = _build_summary_prompt(
                existing.summary_json if existing else None, segment_messages
            )
        except Exception as exc:  # noqa: BLE001 - best-effort，不能让异常抛进 BackgroundTasks
            logger.warning(
                "conversation_summary_prepare_failed", error=str(exc), parent_kind=parent_kind, parent_id=parent_id
            )
            return

        try:
            raw_response = await _call_summary_llm(
                prompt, parent_kind=parent_kind, parent_id=parent_id
            )
            new_summary = _parse_summary_response(raw_response)
        except Exception as exc:
            logger.warning(
                "conversation_summary_llm_failed",
                error_type=type(exc).__name__,
                error=repr(exc),
                parent_kind=parent_kind,
                parent_id=parent_id,
            )
            return
        if new_summary is None:
            logger.warning(
                "conversation_summary_parse_failed",
                parent_kind=parent_kind,
                parent_id=parent_id,
                raw_preview=raw_response[:300],
            )
            return

        await store.upsert_summary(
            db,
            parent_kind=parent_kind,
            parent_id=parent_id,
            summary_json=new_summary,
            covered_through_seq=target_covered_seq,
            source_model=_SUMMARY_MODEL,
            prompt_version=_PROMPT_VERSION,
            tokens_before=None,
            tokens_after=None,
            status="ready",
        )


async def _load_latest_seq(db: AsyncSession, parent_column, parent_id: str) -> int:
    result = await db.execute(select(func.max(ConversationMessage.seq)).where(parent_column == parent_id))
    return result.scalar() or 0


async def _load_segment(
    db: AsyncSession,
    parent_column,
    parent_id: str,
    covered_through_seq: int,
    target_covered_seq: int,
) -> list[ConversationMessage]:
    result = await db.execute(
        select(ConversationMessage)
        .where(
            parent_column == parent_id,
            ConversationMessage.seq > covered_through_seq,
            ConversationMessage.seq <= target_covered_seq,
        )
        .order_by(ConversationMessage.seq)
    )
    return list(result.scalars().all())
