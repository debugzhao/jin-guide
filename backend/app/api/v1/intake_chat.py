"""
Intake Chat API — 建档前 Chat-first 聊天（IntakeAgent）

Endpoints:
  GET    /intake/conversations             — list current owner_key 下的会话（游标分页，侧栏用）
  PATCH  /intake/conversations/{id}         — 重命名会话
  DELETE /intake/conversations/{id}         — 软删除会话
  POST   /intake/chat                       — send message, SSE streaming response
  GET    /intake/chat/history               — fetch conversation history (cold layer)

多会话模型：`intake_conversations.id` 即会话/thread id，不传 `conversation_id`
时后端在首条用户消息产出后懒创建新会话（避免"新建对话"点一下就产生空行）；
传了则校验该会话确实属于当前 owner_key 且未被删除后追加。取代旧版
`/profile/intent` 二分类接口：这里是一段真正的多轮流式聊天，命中建档意图时
通过 SSE `trigger_profile_capture` 事件通知前端内联渲染建档表单，见
`docs/frontend-prd-v2.md` §Chat-first 建档入口、`docs/backend-prd-v2.md` §5.6b。

Redis/PostgreSQL persistence mechanics (key shape, identity resolution, CAS
writes, DB failure logging) live in app.services.conversation_store, shared
with ConversationAgent's chat.py — see docs/memory-architecture.md §六 P0.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
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
from app.services import conversation_store as store

router = APIRouter()

_NAMESPACE = "intake"
_DAILY_LIMIT = 30
_MAX_MESSAGE_LENGTH = 200
_TITLE_MAX_LENGTH = 20
_RENAME_TITLE_MAX_LENGTH = 50
_TITLE_SUMMARY_MODEL = "profile-agent"  # 轻量虚拟模型，见 litellm_config.yaml


def _derive_title(message: str) -> str:
    text = " ".join(message.strip().split())
    if len(text) > _TITLE_MAX_LENGTH:
        return text[:_TITLE_MAX_LENGTH] + "…"
    return text


async def _get_owned_conversation(
    db: AsyncSession, owner_key: str, conversation_id: str, *, include_deleted: bool = False
) -> IntakeConversation | None:
    conditions = [
        IntakeConversation.id == conversation_id,
        IntakeConversation.owner_key == owner_key,
    ]
    if not include_deleted:
        conditions.append(IntakeConversation.deleted_at.is_(None))
    result = await db.execute(select(IntakeConversation).where(*conditions))
    return result.scalar_one_or_none()


async def _summarize_title(message: str, full_response: str) -> str | None:
    """用轻量模型把首条消息拟成一句自然标题，失败返回 None（调用方 fallback 到截断标题）。"""
    prompt = (
        "为下面这轮高考志愿咨询对话拟一个不超过 14 个字的简短标题，"
        "只输出标题本身，不要引号、句末标点或任何解释。\n"
        f"用户：{message}\n"
        f"助手：{full_response[:200]}"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.litellm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.litellm_master_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _TITLE_SUMMARY_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                # kimi-k2.6 是推理模型，即使这么简单的任务也会先输出几百字的
                # reasoning_content 才产出最终 content——实测 max_tokens=30~150 时
                # token 预算全部耗在推理过程上，content 永远是空字符串，必须给够预算。
                "max_tokens": 500,
                # Moonshot Kimi 只允许 temperature=1，传其他值会被 LiteLLM 直接 400（见
                # backend/app/agent/intake_agent.py 里同样固定传 1 的先例）
                "temperature": 1,
            },
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
    text = text.strip("\"'“”。.， ").strip()
    if not text:
        return None
    return text[:_TITLE_MAX_LENGTH]


async def _maybe_upgrade_title(
    owner_key: str, conversation_id: str, seed_title: str, message: str, full_response: str
) -> None:
    """
    Best-effort 后台任务（FastAPI BackgroundTasks，允许进程重启丢失——只是标题从截断态
    升级成 LLM 摘要，不是需要可靠交付的业务数据，符合 CLAUDE.md 对 BackgroundTasks 的使用边界）：
    把首条消息截断生成的标题升级成更自然的一句话摘要。只在标题仍是创建时的截断态（没被用户
    手动改过）才覆盖，失败/超时静默跳过。
    """
    from app.database import async_session_maker

    try:
        new_title = await _summarize_title(message, full_response)
    except Exception:
        return
    if not new_title or new_title == seed_title:
        return

    try:
        async with async_session_maker() as db:
            result = await db.execute(
                select(IntakeConversation).where(
                    IntakeConversation.id == conversation_id,
                    IntakeConversation.owner_key == owner_key,
                    IntakeConversation.title == seed_title,
                )
            )
            conv = result.scalar_one_or_none()
            if conv:
                conv.title = new_title
                await db.commit()
    except Exception:
        pass


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


@router.get("/conversations", response_model=IntakeConversationListOut)
async def list_intake_conversations(
    cursor: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """当前 owner_key 下的建档聊天会话列表，游标分页 (CLAUDE.md「分页规范」)，按最近活跃倒序。"""
    owner_key = store.owner_key(identity)
    if not owner_key:
        return IntakeConversationListOut(items=[], next_cursor=None, has_more=False)

    stmt = select(IntakeConversation).where(
        IntakeConversation.owner_key == owner_key, IntakeConversation.deleted_at.is_(None)
    )

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


class IntakeConversationRenameIn(BaseModel):
    title: str


@router.patch("/conversations/{conversation_id}", response_model=IntakeConversationListItem)
async def rename_intake_conversation(
    conversation_id: str,
    body: IntakeConversationRenameIn,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """重命名会话，仅限当前 owner_key 拥有的会话。不改变 updated_at——重命名不算"活跃"，
    避免侧栏排序因为改名而跳动。"""
    owner_key = store.require_owner_key(identity)

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="标题不能为空")
    title = title[:_RENAME_TITLE_MAX_LENGTH]

    conv = await _get_owned_conversation(db, owner_key, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    conv.title = title
    await db.commit()

    return IntakeConversationListItem(id=conv.id, title=conv.title, updated_at=conv.updated_at.isoformat())


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_intake_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """软删除会话（Redis 热层直接物理删，Postgres 冷层打 deleted_at 标记）。"""
    owner_key = store.require_owner_key(identity)

    conv = await _get_owned_conversation(db, owner_key, conversation_id)
    if not conv:
        return

    conv.deleted_at = datetime.now(UTC)
    await db.commit()

    await store.delete_history_from_redis(store.history_key(_NAMESPACE, owner_key, conversation_id))


@router.post("/chat")
async def intake_chat(
    body: IntakeChatIn,
    background_tasks: BackgroundTasks,
    request: Request,
    identity: Identity = Depends(get_identity),
):
    """
    Send a message to IntakeAgent. Returns an SSE stream with
    token / trigger_profile_capture / done / compliance_warning / error events.

    Rate limit: 30 messages per identity per day (across all of that identity's conversations).
    """
    owner_key = store.require_owner_key(identity)

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

    count = await store.check_and_increment_rate_limit(_NAMESPACE, owner_key)
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

    redis_key = store.history_key(_NAMESPACE, owner_key, conversation_id)
    history = await store.load_history_from_redis(redis_key)

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

                new_messages = [
                    {"role": "user", "content": message, "created_at": datetime.now(UTC).isoformat()},
                    {
                        "role": "assistant",
                        "content": full_response,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                ]

                def build_new_messages(current: list[dict]) -> list[dict]:
                    return current + new_messages

                await store.append_history_to_redis(redis_key, new_messages)

                seed_title = _derive_title(message) if is_new_conversation else None

                # 持久化在 yield done 之前完成：客户端收到 done 后会立即用 conversation_id
                # 刷新侧栏会话列表，必须保证这时数据库已经能查到这条会话，否则会有竞态
                # （侧栏刷新跑在 DB 写入提交之前，读到的还是旧列表）。
                async with async_session_maker() as persist_db:
                    await store.upsert_conversation_row(
                        persist_db,
                        model_cls=IntakeConversation,
                        match=(
                            IntakeConversation.id == conversation_id,
                            IntakeConversation.owner_key == owner_key,
                            IntakeConversation.deleted_at.is_(None),
                        ),
                        build_new_messages=build_new_messages,
                        make_new_row=lambda msgs: IntakeConversation(
                            id=conversation_id,
                            owner_key=owner_key,
                            title=seed_title,
                            messages_json=msgs,
                        ),
                        log_context={"conversation_id": conversation_id, "owner_key": owner_key},
                    )

                if seed_title:
                    # 标题升级是纯锦上添花，不阻塞 done 事件；进程重启丢失也无所谓
                    background_tasks.add_task(
                        _maybe_upgrade_title, owner_key, conversation_id, seed_title, message, full_response
                    )

                yield f"event: done\ndata: {json.dumps({'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"

            elif event_type == "error":
                payload = json.dumps({"message": event.get("message", "未知错误")}, ensure_ascii=False)
                yield f"event: error\ndata: {payload}\n\n"
                return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        # StreamingResponse 是我们手动构造返回的，FastAPI 不会像处理普通返回值那样自动挂载
        # 注入的 background_tasks——必须显式传进来，否则 add_task 注册的任务永远不会被执行。
        background=background_tasks,
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
    owner_key = store.owner_key(identity)
    if not owner_key or not conversation_id:
        return IntakeChatHistoryOut(messages=[], total=0)

    conv = await _get_owned_conversation(db, owner_key, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    messages = await store.load_history_from_redis(store.history_key(_NAMESPACE, owner_key, conversation_id))
    if not messages:
        messages = conv.messages_json or []

    return IntakeChatHistoryOut(messages=messages, total=len(messages))
