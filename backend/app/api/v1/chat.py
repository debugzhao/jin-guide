"""
Chat API — 报告问答 ConversationAgent

Endpoints:
  POST   /reports/{report_id}/chat          — send message, SSE streaming response
  GET    /reports/{report_id}/chat/history  — fetch conversation history (cold layer)
  DELETE /reports/{report_id}/chat          — clear conversation history
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.conversation_agent import stream_conversation_response
from app.api.dependencies import Identity, get_identity
from app.config import settings
from app.database import get_db
from app.models.conversation import ReportConversation
from app.models.report import Report

router = APIRouter()

_DAILY_LIMIT = 30
_MAX_MESSAGES_STORED = 50
_REDIS_HISTORY_TTL = 7 * 24 * 3600  # 7 days
_MAX_MESSAGE_LENGTH = 200

# ── Identity ─────────────────────────────────────────────────────────────────

def _owner_key(identity: Identity) -> str | None:
    """Redis/rate-limit owner key: real user id, or anon:{anonymous_id} for
    anonymous sessions. Must stay the single source of truth used by the
    send/history/clear endpoints alike — a per-endpoint fallback (e.g. client
    IP) will drift from this and desync Redis history across the three routes."""
    if identity.user:
        return identity.user.id
    if identity.anonymous_id:
        return f"anon:{identity.anonymous_id}"
    return None


def _require_owner_key(identity: Identity) -> str:
    owner_key = _owner_key(identity)
    if not owner_key:
        raise HTTPException(
            status_code=401,
            detail="需要先建立匿名会话或登录才能进行报告问答，请先调用 /auth/anonymous-session",
        )
    return owner_key


# ── Redis helpers ──────────────────────────────────────────────────────────────

def _rate_limit_key(owner_key: str) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    return f"chat:daily:{owner_key}:{today}"


def _history_key(report_id: str, owner_key: str) -> str:
    return f"chat:history:{report_id}:{owner_key}"


async def _check_and_increment_rate_limit(owner_key: str) -> int:
    """
    Increment today's message counter for the owner.
    Returns the new count. Caller should check count > _DAILY_LIMIT.
    """
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = _rate_limit_key(owner_key)
        count = await redis_client.incr(key)
        if count == 1:
            # Set expiry to end of UTC day
            now = datetime.now(UTC)
            tomorrow = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            ttl = int((tomorrow - now).total_seconds())
            await redis_client.expire(key, ttl)
        return count
    finally:
        await redis_client.aclose()


async def _load_history_from_redis(report_id: str, owner_key: str) -> list[dict]:
    """Load conversation history from Redis hot layer."""
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis_client.get(_history_key(report_id, owner_key))
        if raw:
            return json.loads(raw)
        return []
    except Exception:
        return []
    finally:
        await redis_client.aclose()


async def _save_history_to_redis(
    report_id: str, owner_key: str, messages: list[dict]
) -> None:
    """Write conversation history to Redis hot layer."""
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = _history_key(report_id, owner_key)
        await redis_client.setex(key, _REDIS_HISTORY_TTL, json.dumps(messages, ensure_ascii=False))
    except Exception:
        pass
    finally:
        await redis_client.aclose()


def _db_owner_filter(user_id: str | None, anonymous_id: str | None):
    """
    Row-scoping filter for report_conversations. Logged-in users are scoped by
    user_id; anonymous sessions must additionally match anonymous_id — matching
    only `user_id IS NULL` would let every anonymous visitor share one row
    (and read each other's history) for the same report_id.
    """
    if user_id:
        return (ReportConversation.user_id == user_id,)
    return (
        ReportConversation.user_id.is_(None),
        ReportConversation.anonymous_id == anonymous_id,
    )


async def _persist_history_to_db(
    db: AsyncSession,
    report_id: str,
    user_id: str | None,
    anonymous_id: str | None,
    messages: list[dict],
) -> None:
    """Upsert conversation history to PostgreSQL cold layer."""
    try:
        result = await db.execute(
            select(ReportConversation).where(
                ReportConversation.report_id == report_id,
                *_db_owner_filter(user_id, anonymous_id),
            )
        )
        conv = result.scalar_one_or_none()
        if conv:
            conv.messages_json = messages[-_MAX_MESSAGES_STORED:]
            conv.updated_at = datetime.now(UTC)
        else:
            conv = ReportConversation(
                id=str(uuid4()),
                report_id=report_id,
                user_id=user_id,
                anonymous_id=anonymous_id,
                messages_json=messages[-_MAX_MESSAGES_STORED:],
            )
            db.add(conv)
        await db.commit()
    except Exception:
        pass  # DB persistence is best-effort; Redis is the hot layer


# ── Schemas ────────────────────────────────────────────────────────────────────

class ChatIn(BaseModel):
    message: str


class ChatHistoryOut(BaseModel):
    report_id: str
    messages: list[dict]
    total: int


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/{report_id}/chat")
async def chat_with_report(
    report_id: str,
    body: ChatIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """
    Send a message to ConversationAgent about a specific report.
    Returns an SSE stream with token / citation / done / compliance_warning events.

    Rate limit: 30 messages per user per day.
    Report must have status=completed.
    """
    # ── Validate report ────────────────────────────────────────────────────
    if report_id == "demo-report":
        from app.api.v1.mock_data import MOCK_REPORT_PLAN, MOCK_REPORT_EVIDENCE
        report_plan_json = MOCK_REPORT_PLAN
        report_evidence_json = MOCK_REPORT_EVIDENCE
    else:
        result = await db.execute(
            select(Report).where(Report.id == report_id, Report.deleted_at.is_(None))
        )
        report = result.scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=404, detail="报告不存在")
        if report.status != "completed":
            raise HTTPException(status_code=422, detail="报告尚未生成完成，无法进行问答")
        report_plan_json = report.plan_json
        report_evidence_json = report.evidence_json

    # ── Validate message ───────────────────────────────────────────────────
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="消息不能为空")
    if len(message) > _MAX_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=422, detail=f"消息不能超过 {_MAX_MESSAGE_LENGTH} 个字符"
        )

    # ── Rate limit ─────────────────────────────────────────────────────────
    owner_key = _require_owner_key(identity)
    count = await _check_and_increment_rate_limit(owner_key)
    if count > _DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": f"今日问答次数已达上限（{_DAILY_LIMIT}条），明日 0 点重置",
                "limit": _DAILY_LIMIT,
                "used": count - 1,
            },
        )

    # ── Load history ───────────────────────────────────────────────────────
    history = await _load_history_from_redis(report_id, owner_key)

    # ── Stream response ────────────────────────────────────────────────────
    async def event_generator():
        full_response = ""
        citations = []

        async for event in stream_conversation_response(
            plan_json=report_plan_json,
            evidence_json=report_evidence_json,
            history=history,
            user_message=message,
        ):
            event_type = event.get("type")

            if event_type == "token":
                payload = json.dumps({"content": event["content"]}, ensure_ascii=False)
                yield f"event: token\ndata: {payload}\n\n"

            elif event_type == "citation":
                citations.append({"source_id": event["source_id"], "text": event["text"]})
                payload = json.dumps(
                    {"source_id": event["source_id"], "text": event["text"]},
                    ensure_ascii=False,
                )
                yield f"event: citation\ndata: {payload}\n\n"

            elif event_type == "compliance_warning":
                payload = json.dumps({"issues": event["issues"]}, ensure_ascii=False)
                yield f"event: compliance_warning\ndata: {payload}\n\n"

            elif event_type == "done":
                full_response = event.get("full_response", "")
                payload = json.dumps(
                    {"citations": citations, "message_id": str(uuid4())},
                    ensure_ascii=False,
                )
                yield f"event: done\ndata: {payload}\n\n"

                # Persist history asynchronously
                new_history = history + [
                    {"role": "user", "content": message, "created_at": datetime.now(UTC).isoformat()},
                    {
                        "role": "assistant",
                        "content": full_response,
                        "citations": citations,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                ]
                new_history = new_history[-_MAX_MESSAGES_STORED:]
                await _save_history_to_redis(report_id, owner_key, new_history)
                # Best-effort DB persist (fire and forget — use separate session)
                if report_id != "demo-report":
                    from app.database import async_session_maker
                    async with async_session_maker() as persist_db:
                        await _persist_history_to_db(
                            persist_db,
                            report_id,
                            identity.user.id if identity.user else None,
                            identity.anonymous_id if not identity.user else None,
                            new_history,
                        )

            elif event_type == "error":
                payload = json.dumps({"message": event.get("message", "未知错误")}, ensure_ascii=False)
                yield f"event: error\ndata: {payload}\n\n"
                return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{report_id}/chat/history", response_model=ChatHistoryOut)
async def get_chat_history(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """
    Return the conversation history for a report.
    Tries Redis hot layer first; falls back to PostgreSQL.
    """
    owner_key = _require_owner_key(identity)
    db_user_id = identity.user.id if identity.user else None
    db_anonymous_id = identity.anonymous_id if not identity.user else None

    if report_id == "demo-report":
        messages = await _load_history_from_redis(report_id, owner_key)
    else:
        result = await db.execute(
            select(Report).where(Report.id == report_id, Report.deleted_at.is_(None))
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="报告不存在")

        # Try hot layer first
        messages = await _load_history_from_redis(report_id, owner_key)

        if not messages:
            # Fall back to DB
            conv_result = await db.execute(
                select(ReportConversation).where(
                    ReportConversation.report_id == report_id,
                    *_db_owner_filter(db_user_id, db_anonymous_id),
                )
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                messages = conv.messages_json or []

    return ChatHistoryOut(
        report_id=report_id,
        messages=messages,
        total=len(messages),
    )


@router.delete("/{report_id}/chat", status_code=204)
async def clear_chat_history(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """Clear conversation history from both Redis and PostgreSQL."""
    owner_key = _require_owner_key(identity)
    db_user_id = identity.user.id if identity.user else None
    db_anonymous_id = identity.anonymous_id if not identity.user else None

    # Clear Redis
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.delete(_history_key(report_id, owner_key))
    finally:
        await redis_client.aclose()

    if report_id != "demo-report":
        result = await db.execute(
            select(Report).where(Report.id == report_id, Report.deleted_at.is_(None))
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="报告不存在")

        # Clear DB
        conv_result = await db.execute(
            select(ReportConversation).where(
                ReportConversation.report_id == report_id,
                *_db_owner_filter(db_user_id, db_anonymous_id),
            )
        )
        conv = conv_result.scalar_one_or_none()
        if conv:
            conv.messages_json = []
            conv.updated_at = datetime.now(UTC)
            await db.commit()
