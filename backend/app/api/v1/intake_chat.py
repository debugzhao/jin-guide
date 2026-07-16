"""
Intake Chat API — 建档前 Chat-first 聊天（IntakeAgent）

Endpoints:
  GET    /intake/conversations — list current owner_key 下的会话（游标分页，侧栏用）
  POST   /intake/chat          — send message, SSE streaming response
  GET    /intake/chat/history  — fetch conversation history (cold layer)
  DELETE /intake/chat          — clear a conversation's history

多会话模型：`intake_conversations.id` 即会话/thread id，不传 `conversation_id`
时后端在首条用户消息产出后懒创建新会话（避免"新建对话"点一下就产生空行）；
传了则校验该会话确实属于当前 owner_key 后追加。取代旧版 `/profile/intent`
二分类接口：这里是一段真正的多轮流式聊天，命中建档意图时通过 SSE
`trigger_profile_capture` 事件通知前端内联渲染建档表单，见
`docs/frontend-prd-v2.md` §Chat-first 建档入口、`docs/backend-prd-v2.md` §5.6b。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intake_agent import stream_intake_response
from app.api.cursor import decode_cursor, encode_cursor
from app.api.dependencies import Identity, get_identity
from app.config import settings
from app.database import get_db
from app.models.conversation import IntakeConversation

router = APIRouter()

_DAILY_LIMIT = 30
_MAX_MESSAGES_STORED = 50
_REDIS_HISTORY_TTL = 7 * 24 * 3600  # 7 days
_MAX_MESSAGE_LENGTH = 200
_TITLE_MAX_LENGTH = 20


def _owner_key(identity: Identity) -> str | None:
    if identity.user:
        return identity.user.id
    if identity.anonymous_id:
        return f"anon:{identity.anonymous_id}"
    return None


def _rate_limit_key(owner_key: str) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    return f"intake:daily:{owner_key}:{today}"


def _history_key(owner_key: str, conversation_id: str) -> str:
    return f"intake:history:{owner_key}:{conversation_id}"


def _derive_title(message: str) -> str:
    text = " ".join(message.strip().split())
    if len(text) > _TITLE_MAX_LENGTH:
        return text[:_TITLE_MAX_LENGTH] + "…"
    return text


async def _check_and_increment_rate_limit(owner_key: str) -> int:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = _rate_limit_key(owner_key)
        count = await redis_client.incr(key)
        if count == 1:
            now = datetime.now(UTC)
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            await redis_client.expire(key, int((tomorrow - now).total_seconds()))
        return count
    finally:
        await redis_client.aclose()


async def _load_history_from_redis(owner_key: str, conversation_id: str) -> list[dict]:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis_client.get(_history_key(owner_key, conversation_id))
        return json.loads(raw) if raw else []
    except Exception:
        return []
    finally:
        await redis_client.aclose()


async def _save_history_to_redis(owner_key: str, conversation_id: str, messages: list[dict]) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.setex(
            _history_key(owner_key, conversation_id), _REDIS_HISTORY_TTL, json.dumps(messages, ensure_ascii=False)
        )
    except Exception:
        pass
    finally:
        await redis_client.aclose()


async def _get_owned_conversation(
    db: AsyncSession, owner_key: str, conversation_id: str
) -> IntakeConversation | None:
    result = await db.execute(
        select(IntakeConversation).where(
            IntakeConversation.id == conversation_id,
            IntakeConversation.owner_key == owner_key,
        )
    )
    return result.scalar_one_or_none()


async def _persist_history_to_db(
    db: AsyncSession,
    owner_key: str,
    conversation_id: str,
    messages: list[dict],
    *,
    seed_title: str | None,
) -> None:
    """Upsert conversation history to PostgreSQL cold layer (best-effort)."""
    try:
        conv = await _get_owned_conversation(db, owner_key, conversation_id)
        if conv:
            conv.messages_json = messages[-_MAX_MESSAGES_STORED:]
            conv.updated_at = datetime.now(UTC)
        else:
            conv = IntakeConversation(
                id=conversation_id,
                owner_key=owner_key,
                title=seed_title,
                messages_json=messages[-_MAX_MESSAGES_STORED:],
            )
            db.add(conv)
        await db.commit()
    except Exception:
        pass  # DB persistence is best-effort; Redis is the hot layer


class IntakeChatIn(BaseModel):
    message: str
    # 不传则懒创建新会话；传了则必须是当前 owner_key 已拥有的会话
    conversation_id: Optional[str] = None


class IntakeChatHistoryOut(BaseModel):
    messages: list[dict]
    total: int


class IntakeConversationListItem(BaseModel):
    id: str
    title: Optional[str]
    updated_at: str


class IntakeConversationListOut(BaseModel):
    items: list[IntakeConversationListItem]
    next_cursor: Optional[str]
    has_more: bool


def _require_owner_key(identity: Identity) -> str:
    owner_key = _owner_key(identity)
    if not owner_key:
        raise HTTPException(
            status_code=401,
            detail="需要先建立匿名会话或登录才能开始对话，请先调用 /auth/anonymous-session",
        )
    return owner_key


@router.get("/conversations", response_model=IntakeConversationListOut)
async def list_intake_conversations(
    cursor: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """当前 owner_key 下的建档聊天会话列表，游标分页 (CLAUDE.md「分页规范」)，按最近活跃倒序。"""
    owner_key = _owner_key(identity)
    if not owner_key:
        return IntakeConversationListOut(items=[], next_cursor=None, has_more=False)

    stmt = select(IntakeConversation).where(IntakeConversation.owner_key == owner_key)

    if cursor:
        try:
            cur_updated_at, cur_id = decode_cursor(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid cursor")
        stmt = stmt.where(
            (IntakeConversation.updated_at < cur_updated_at)
            | ((IntakeConversation.updated_at == cur_updated_at) & (IntakeConversation.id < cur_id))
        )

    stmt = stmt.order_by(IntakeConversation.updated_at.desc(), IntakeConversation.id.desc()).limit(limit + 1)

    result = await db.execute(stmt)
    conversations = result.scalars().all()
    has_more = len(conversations) > limit
    conversations = conversations[:limit]
    next_cursor = (
        encode_cursor(conversations[-1].updated_at, conversations[-1].id) if has_more and conversations else None
    )

    return IntakeConversationListOut(
        items=[
            IntakeConversationListItem(id=c.id, title=c.title, updated_at=c.updated_at.isoformat())
            for c in conversations
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post("/chat")
async def intake_chat(
    body: IntakeChatIn,
    request: Request,
    identity: Identity = Depends(get_identity),
):
    """
    Send a message to IntakeAgent. Returns an SSE stream with
    token / trigger_profile_capture / done / compliance_warning / error events.

    Rate limit: 30 messages per identity per day (across all of that identity's conversations).
    """
    owner_key = _require_owner_key(identity)

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="消息不能为空")
    if len(message) > _MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=422, detail=f"消息不能超过 {_MAX_MESSAGE_LENGTH} 个字符")

    from app.database import async_session_maker

    is_new_conversation = not body.conversation_id
    if body.conversation_id:
        async with async_session_maker() as check_db:
            conv = await _get_owned_conversation(check_db, owner_key, body.conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        conversation_id = body.conversation_id
    else:
        conversation_id = str(uuid4())

    count = await _check_and_increment_rate_limit(owner_key)
    if count > _DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": f"今日对话次数已达上限（{_DAILY_LIMIT}条），明日 0 点重置",
                "limit": _DAILY_LIMIT,
                "used": count - 1,
            },
        )

    history = await _load_history_from_redis(owner_key, conversation_id)

    async def event_generator():
        full_response = ""

        async for event in stream_intake_response(history=history, user_message=message):
            event_type = event.get("type")

            if event_type == "token":
                payload = json.dumps({"content": event["content"]}, ensure_ascii=False)
                yield f"event: token\ndata: {payload}\n\n"

            elif event_type == "trigger_profile_capture":
                yield "event: trigger_profile_capture\ndata: {}\n\n"

            elif event_type == "compliance_warning":
                payload = json.dumps({"issues": event["issues"]}, ensure_ascii=False)
                yield f"event: compliance_warning\ndata: {payload}\n\n"

            elif event_type == "done":
                full_response = event.get("full_response", "")

                new_history = history + [
                    {"role": "user", "content": message, "created_at": datetime.now(UTC).isoformat()},
                    {
                        "role": "assistant",
                        "content": full_response,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                ]
                new_history = new_history[-_MAX_MESSAGES_STORED:]
                await _save_history_to_redis(owner_key, conversation_id, new_history)

                # 持久化在 yield done 之前完成：客户端收到 done 后会立即用 conversation_id
                # 刷新侧栏会话列表，必须保证这时数据库已经能查到这条会话，否则会有竞态
                # （侧栏刷新跑在 DB 写入提交之前，读到的还是旧列表）。
                async with async_session_maker() as persist_db:
                    await _persist_history_to_db(
                        persist_db,
                        owner_key,
                        conversation_id,
                        new_history,
                        seed_title=_derive_title(message) if is_new_conversation else None,
                    )

                yield f"event: done\ndata: {json.dumps({'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"

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


@router.get("/chat/history", response_model=IntakeChatHistoryOut)
async def get_intake_chat_history(
    conversation_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """Return one conversation's history. No conversation_id → empty (fresh conversation state)."""
    owner_key = _owner_key(identity)
    if not owner_key or not conversation_id:
        return IntakeChatHistoryOut(messages=[], total=0)

    conv = await _get_owned_conversation(db, owner_key, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    messages = await _load_history_from_redis(owner_key, conversation_id)
    if not messages:
        messages = conv.messages_json or []

    return IntakeChatHistoryOut(messages=messages, total=len(messages))


@router.delete("/chat", status_code=204)
async def clear_intake_chat_history(
    conversation_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """Delete one conversation's history (Redis + PostgreSQL)."""
    owner_key = _owner_key(identity)
    if not owner_key or not conversation_id:
        return

    conv = await _get_owned_conversation(db, owner_key, conversation_id)
    if not conv:
        return

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.delete(_history_key(owner_key, conversation_id))
    finally:
        await redis_client.aclose()

    await db.delete(conv)
    await db.commit()
