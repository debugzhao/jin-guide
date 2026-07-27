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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.conversation import ConversationMessage
from app.services import conversation_store as store

logger = structlog.get_logger()

_SUMMARY_MODEL = "profile-agent"  # 轻量虚拟模型，见 litellm_config.yaml
_PROMPT_VERSION = "v1"
_SUMMARY_KEYS = (
    "confirmed_facts",
    "preferences",
    "rejected_options",
    "previous_decisions",
    "open_questions",
)


def _build_summary_prompt(previous_summary: dict | None, segment_messages: list[ConversationMessage]) -> str:
    segment_text = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}：{m.content}" for m in segment_messages
    )
    previous_text = (
        json.dumps(previous_summary, ensure_ascii=False) if previous_summary else "（还没有历史摘要）"
    )
    return (
        "你在维护一段高考志愿咨询对话的结构化摘要，用于在对话变长后仍能记住早期关键信息。\n"
        "下面是已有的摘要（JSON），以及本轮需要并入摘要、即将从原文窗口中滑出的对话片段。\n"
        "请基于两者输出【更新后】的完整摘要 JSON（覆盖式输出全部字段，不要只输出增量）。字段含义：\n"
        "- confirmed_facts：用户明确给出的硬事实（预算、省份、分数、位次等），新事实覆盖旧值；\n"
        "- preferences：用户表达过的偏好（城市、专业方向等）；\n"
        "- rejected_options：用户明确排除/不考虑的选项；\n"
        "- previous_decisions：本轮对话中做过的决定或结论；\n"
        "- open_questions：还没解决、需要后续跟进的问题。\n"
        "每个字段的值必须是【字符串数组】，即使只有一条也要用数组包裹（例如\n"
        '"confirmed_facts": ["预算：12万元/年"]，不要输出成对象 {\"annual_budget\": \"12万元/年\"}）。\n'
        "只输出 JSON 本身，不要任何解释文字，不要 markdown 代码块围栏。\n\n"
        f"已有摘要：\n{previous_text}\n\n"
        f"本轮需要并入摘要的对话片段：\n{segment_text}\n"
    )


async def _call_summary_llm(prompt: str) -> str:
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
    async with httpx.AsyncClient(timeout=240.0) as client:
        async with client.stream(
            "POST",
            f"{settings.litellm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.litellm_master_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _SUMMARY_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                # kimi-k2.6 是推理模型，结构化摘要比 intake_chat.py 的标题摘要复杂得多，
                # 必须给足够预算覆盖 reasoning_content + 最终 JSON，否则 content 为空字符串。
                "max_tokens": 3000,
                # Moonshot Kimi 只允许 temperature=1，传其他值会被 LiteLLM 直接 400。
                "temperature": 1,
                "stream": True,
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
    if not isinstance(parsed, dict):
        return None
    # 缺失字段补空数组；即使 Prompt 明确要求数组，kimi-k2.6 仍偶尔把
    # confirmed_facts 这类字段输出成 {"annual_budget": "12万元/年"} 这样的对象
    # ——统一压平成字符串数组，保证下游渲染（_build_summary_block）和存库结构稳定，
    # 不依赖模型每次都严格遵守格式指令。
    return {key: _normalize_summary_field(parsed.get(key)) for key in _SUMMARY_KEYS}


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
            raw_response = await _call_summary_llm(prompt)
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
