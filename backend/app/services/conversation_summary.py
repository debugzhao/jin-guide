"""
Structured incremental conversation summary — see docs/memory-architecture.md
§六 P2.

Agents only ever see the last MAX_HISTORY_MESSAGES raw messages (10 for
ConversationAgent, 16 for IntakeAgent). Once a conversation runs longer than
that, earlier turns simply never enter the prompt again — nothing captured
them. This module maintains a structured JSON summary (confirmed_facts /
preferences / rejected_options / previous_decisions / open_questions) that
covers messages once they age out of that window, so facts like "budget is
50k" stay visible to the agent long after the turn that stated it has
scrolled away.

The summary is not a source of truth — ConversationMessage rows are — so
every regeneration records its model, prompt version, and covered range
(see ConversationSummary). Generation is best-effort (same reliability tier
as intake_chat.py's title upgrade, triggered via FastAPI BackgroundTasks):
a failure leaves the previous summary untouched, and callers always still
have the raw recent-message window as a fallback regardless of whether a
summary exists.
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


# ConversationMessage-side column lookup, kept local to this module —
# ConversationSummary's own equivalent columns are resolved inside
# conversation_store.py's load_summary/upsert_summary from the same
# `parent_kind` string, so the two models' columns are never crossed (see
# the comment on conversation_store._MESSAGE_PARENT_COLUMNS for the bug this
# avoids: passing one model's column into a query against the other model
# silently produces a cross join instead of an error).
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
    Best-effort background task (FastAPI BackgroundTasks — same reliability
    tier as intake_chat.py's _maybe_upgrade_title): check whether a full
    window's worth of messages has aged out since the last summary update,
    and if so regenerate the structured summary covering them.

    `parent_kind` is "report" or "intake"; `window_size` should match the
    corresponding agent's MAX_HISTORY_MESSAGES so the summary picks up
    exactly where the raw recent-message window leaves off, with no gap and
    no overlap.
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
        except Exception as exc:  # noqa: BLE001 - best-effort, must not raise into BackgroundTasks
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
