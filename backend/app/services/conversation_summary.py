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
import uuid

import httpx
import redis.asyncio as aioredis
import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.conversation import ConversationMessage
from app.prompts import prompt_registry, wrap_untrusted_context
from app.prompts.tracing import track_prompt_invocation
from app.services import conversation_store as store

logger = structlog.get_logger()

_PROMPT = prompt_registry.get("conversation_summary")
_SUMMARY_MODEL = _PROMPT.model.alias
_PROMPT_VERSION = _PROMPT.version
# 固定指令只进入 system；历史摘要和对话原文都是用户可影响的动态数据，必须作为
# 转义后的不可信数据块传递（与 conversation_agent.py/intake_agent.py 同一约定），
# 否则对话里刻意构造的"忽略以上指令""新任务是……"之类文字可能被当成对摘要模型
# 本身的指令执行，污染写入 DB 的结构化摘要，并在后续每一轮对话里持续被引用。
_SYSTEM_PROMPT = _PROMPT.render("system")
_SUMMARY_KEYS = (
    "confirmed_facts",
    "preferences",
    "rejected_options",
    "previous_decisions",
    "open_questions",
)

# 同一会话的摘要生成串行化锁——只有一个进程有权限跑"读旧摘要→调 LLM→写新
# 摘要"这一整套流程，从源头避免两个并发的 BackgroundTasks（例如用户在第一
# 条消息的 SSE 流结束前就发出第二条消息）用各自读到的旧摘要互相覆盖。TTL
# 留出比 LLM 调用超时（见 conversation_summary/v1.yaml 的 timeout_seconds）
# 更宽的余量，防止进程崩溃后锁永久卡死；释放时用 token 做 compare-and-delete，
# 避免释放掉 TTL 到期后被别的任务重新抢到的锁。
_LOCK_KEY_TMPL = "summary:lock:{parent_kind}:{parent_id}"
_LOCK_TTL_MS = (int(_PROMPT.model.timeout_seconds) + 60) * 1000
_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


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


def _build_summary_user_content(previous_summary: dict | None, segment_messages: list[ConversationMessage]) -> str:
    segment_text = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}：{m.content}" for m in segment_messages
    )
    previous_text = (
        json.dumps(previous_summary, ensure_ascii=False) if previous_summary else "（还没有历史摘要）"
    )
    return _PROMPT.render(
        "user",
        previous_summary=wrap_untrusted_context("previous_summary", previous_text),
        conversation_segment=wrap_untrusted_context("conversation_segment", segment_text),
    )


async def _call_summary_llm(
    user_content: str, *, parent_kind: str | None = None, parent_id: str | None = None
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
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
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

    同一 (parent_kind, parent_id) 的生成流程用 Redis 锁串行化——用户在第一
    条消息的 SSE 流结束前发出第二条消息时，两次请求各自的 `done` 分支都会
    挂一个 BackgroundTasks，抢不到锁的一方直接跳过，避免两个任务并发读到
    同一份旧摘要、之后互相覆盖对方已经提交的新结果。
    """
    lock_key = _LOCK_KEY_TMPL.format(parent_kind=parent_kind, parent_id=parent_id)
    lock_token = str(uuid.uuid4())
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        acquired = await redis_client.set(lock_key, lock_token, nx=True, px=_LOCK_TTL_MS)
        if not acquired:
            logger.info(
                "conversation_summary_lock_busy", parent_kind=parent_kind, parent_id=parent_id
            )
            return
        await _generate_summary(parent_kind, parent_id, window_size=window_size)
    finally:
        try:
            await redis_client.eval(_RELEASE_LOCK_LUA, 1, lock_key, lock_token)
        except Exception:  # noqa: BLE001 - 锁释放失败不影响本次结果，TTL 会兜底回收
            logger.warning(
                "conversation_summary_lock_release_failed", parent_kind=parent_kind, parent_id=parent_id
            )
        await redis_client.aclose()


async def _generate_summary(parent_kind: str, parent_id: str, *, window_size: int) -> None:
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

            # 覆盖点必须从"上次覆盖到哪"往前推一个窗口，不能锚定当前最新消息——
            # 否则每来一轮新消息，`latest_seq - covered_through_seq` 都会重新
            # 越过 window_size 触发摘要，但每次只推进一两条，退化成"几乎每轮
            # 都调用一次摘要 LLM"。如果因为服务中断攒下了不止一个窗口的积压，
            # 这里只推进一个窗口，剩余积压会在后续几轮里按同样节奏逐步追上。
            target_covered_seq = covered_through_seq + window_size
            segment_messages = await _load_segment(
                db, parent_column, parent_id, covered_through_seq, target_covered_seq
            )
            if not segment_messages:
                return

            user_content = _build_summary_user_content(
                existing.summary_json if existing else None, segment_messages
            )
        except Exception as exc:  # noqa: BLE001 - best-effort，不能让异常抛进 BackgroundTasks
            logger.warning(
                "conversation_summary_prepare_failed", error=str(exc), parent_kind=parent_kind, parent_id=parent_id
            )
            return

        try:
            raw_response = await _call_summary_llm(
                user_content, parent_kind=parent_kind, parent_id=parent_id
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
            expected_covered_through_seq=covered_through_seq,
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
