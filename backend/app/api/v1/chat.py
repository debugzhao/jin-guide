"""
Chat API — 报告问答 ConversationAgent

Endpoints:
  POST   /reports/{report_id}/chat          — 发送消息，SSE 流式返回
  GET    /reports/{report_id}/chat/history  — 获取会话历史（冷层）
  DELETE /reports/{report_id}/chat          — 清空会话历史

Redis/PostgreSQL 持久化的具体机制（key 结构、身份解析、CAS 写入、DB 失败日志）
统一放在 app.services.conversation_store，与 IntakeAgent 的 intake_chat.py 共用
——详见 docs/memory-architecture.md §六 P0。
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.conversation_agent import MAX_HISTORY_MESSAGES, stream_conversation_response
from app.api.dependencies import Identity, get_identity
from app.config import settings
from app.database import async_session_maker, get_db
from app.models.conversation import ConversationMessage, ReportConversation
from app.models.report import Report
from app.services import conversation_store as store
from app.services.conversation_summary import maybe_generate_summary

router = APIRouter()

_NAMESPACE = "chat"
_DAILY_LIMIT = 30
_MAX_MESSAGE_LENGTH = 200


def _db_owner_filter(user_id: str | None, anonymous_id: str | None) -> tuple:
    """
    report_conversations 的行级过滤条件。已登录用户按 user_id 限定；匿名会话
    必须额外匹配 anonymous_id——如果只匹配 `user_id IS NULL`，同一个 report_id
    下所有匿名访客会共用一行（互相读到对方的历史）。
    """
    if user_id:
        return (ReportConversation.user_id == user_id,)
    return (
        ReportConversation.user_id.is_(None),
        ReportConversation.anonymous_id == anonymous_id,
    )


# ── 数据结构 ────────────────────────────────────────────────────────────────────

class ChatIn(BaseModel):
    message: str


class ChatHistoryOut(BaseModel):
    report_id: str
    messages: list[dict]
    total: int


# ── 接口 ──────────────────────────────────────────────────────────────────────

@router.post("/{report_id}/chat")
async def chat_with_report(
    report_id: str,
    body: ChatIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_identity),
):
    """
    针对某份报告向 ConversationAgent 发送一条消息。
    返回 SSE 流，事件类型包括 token / citation / done / compliance_warning。

    限流：每用户每天 30 条。`settings.dedup_window_minutes` 时间窗内的重复/
    近似重复问题会直接复用缓存回答，不再调用 LLM（docs/backend-prd-v2.md
    §11.4）。报告必须处于 status=completed 状态。
    """
    # ── 校验报告 ────────────────────────────────────────────────────────────
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

    # ── 校验消息内容 ────────────────────────────────────────────────────────
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="消息不能为空")
    if len(message) > _MAX_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=422, detail=f"消息不能超过 {_MAX_MESSAGE_LENGTH} 个字符"
        )

    # ── 限流 ────────────────────────────────────────────────────────────────
    owner_key = store.require_owner_key(identity)
    count = await store.check_and_increment_rate_limit(_NAMESPACE, owner_key)
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

    # ── 加载历史 ────────────────────────────────────────────────────────────
    db_user_id = identity.user.id if identity.user else None
    db_anonymous_id = identity.anonymous_id if not identity.user else None

    redis_key = store.history_key(_NAMESPACE, report_id, owner_key)
    history = await store.load_history_from_redis(redis_key)

    if not history and report_id != "demo-report":
        # Redis 未命中（TTL 过期/重启/故障）时回退到 DB 并回填——统一实现见
        # store.hydrate_history_from_db，GET /chat/history（见下面
        # get_chat_history）用的是同一个函数，不会再各自维护一份。
        conv_result = await db.execute(
            select(ReportConversation).where(
                ReportConversation.report_id == report_id,
                *_db_owner_filter(db_user_id, db_anonymous_id),
            )
        )
        existing_conv = conv_result.scalar_one_or_none()
        if existing_conv:
            history = await store.hydrate_history_from_db(
                db, redis_key, parent_kind="report", parent_id=existing_conv.id
            )

    # ── 重复/相似问题去重：命中且历史回答已完整就复用，不重新调用 LLM ──────────
    # （docs/backend-prd-v2.md §11.4）
    cached = store.find_cached_answer(
        history,
        message,
        window_minutes=settings.dedup_window_minutes,
        similarity_threshold=settings.dedup_similarity_threshold,
    )

    # ── 加载结构化摘要（best-effort；覆盖已经滑出原始历史窗口的消息——见 P2）──
    summary_json: dict | None = None
    if report_id != "demo-report":
        try:
            async with async_session_maker() as summary_db:
                conv_result = await summary_db.execute(
                    select(ReportConversation).where(
                        ReportConversation.report_id == report_id,
                        *_db_owner_filter(db_user_id, db_anonymous_id),
                    )
                )
                conv_row = conv_result.scalar_one_or_none()
                if conv_row:
                    summary_row = await store.load_summary(
                        summary_db,
                        parent_kind="report",
                        parent_id=conv_row.id,
                    )
                    if summary_row:
                        summary_json = summary_row.summary_json
        except Exception:  # noqa: BLE001 - 摘要读取失败不能阻塞聊天
            summary_json = None

    # ── 生成开始前先落一条用户消息 + 空内容的助手占位消息 ──────────────────────
    # "生成开始建空记录，逐步填充"（docs/疑问杂项.md「生成过程中刷新页面丢失聊天
    # 记录」）：不再等 done 事件才一次性写两条消息——这样哪怕浏览器在生成过程中
    # 刷新，GET history 至少能读到已经发出的用户消息和目前为止生成到的部分内容。
    # demo-report 维持原有行为，只写 Redis 不落库（conversation_row_id/
    # assistant_message_id 保持 None，下面的 DB 同步全部自动退化成 no-op）。
    now_iso = datetime.now(UTC).isoformat()
    user_msg_dict = {"role": "user", "content": message, "created_at": now_iso}
    placeholder_msg_dict = {
        "role": "assistant",
        "content": cached["content"] if cached else "",
        "citations": (cached.get("citations") or []) if cached else [],
        "created_at": now_iso,
    }

    conversation_row_id: str | None = None
    assistant_message_id: str | None = None
    if report_id != "demo-report":
        async with async_session_maker() as persist_db:
            conversation_row_id = await store.get_or_create_conversation_row(
                persist_db,
                model_cls=ReportConversation,
                match=(
                    ReportConversation.report_id == report_id,
                    *_db_owner_filter(db_user_id, db_anonymous_id),
                ),
                make_new_row=lambda: ReportConversation(
                    id=str(uuid4()),
                    report_id=report_id,
                    user_id=db_user_id,
                    anonymous_id=db_anonymous_id,
                ),
                log_context={"report_id": report_id, "owner_key": owner_key},
            )
            if conversation_row_id:
                inserted_ids = await store.append_conversation_messages(
                    persist_db,
                    parent_kind="report",
                    parent_id=conversation_row_id,
                    new_messages=[user_msg_dict, placeholder_msg_dict],
                    log_context={"report_id": report_id, "owner_key": owner_key},
                )
                if inserted_ids:
                    assistant_message_id = inserted_ids[-1]

    await store.append_history_to_redis(redis_key, [user_msg_dict, placeholder_msg_dict])

    # ── 流式返回 ────────────────────────────────────────────────────────────
    async def event_generator():
        if cached is not None:
            # 复用命中的历史回答，不调用 ConversationAgent——见上面的去重检查。
            cached_content = cached["content"]
            cached_citations = cached.get("citations") or []
            payload = json.dumps({"content": cached_content}, ensure_ascii=False)
            yield f"event: token\ndata: {payload}\n\n"
            for c in cached_citations:
                cpayload = json.dumps(
                    {"source_id": c.get("source_id"), "text": c.get("text")}, ensure_ascii=False
                )
                yield f"event: citation\ndata: {cpayload}\n\n"

            done_payload = json.dumps(
                {"citations": cached_citations, "message_id": str(uuid4())}, ensure_ascii=False
            )
            yield f"event: done\ndata: {done_payload}\n\n"

            if conversation_row_id:
                background_tasks.add_task(
                    maybe_generate_summary, "report", conversation_row_id, window_size=MAX_HISTORY_MESSAGES,
                )
            return

        full_response = ""
        citations = []
        last_flush = time.monotonic()

        async for event in stream_conversation_response(
            plan_json=report_plan_json,
            evidence_json=report_evidence_json,
            history=history,
            user_message=message,
            summary=summary_json,
            report_id=report_id,
        ):
            event_type = event.get("type")

            if event_type == "token":
                payload = json.dumps({"content": event["content"]}, ensure_ascii=False)
                yield f"event: token\ndata: {payload}\n\n"

                full_response += event["content"]
                now = time.monotonic()
                if now - last_flush >= store.INCREMENTAL_FLUSH_INTERVAL_SECONDS:
                    last_flush = now
                    if assistant_message_id:
                        async with async_session_maker() as flush_db:
                            await store.update_message_content(
                                flush_db, message_id=assistant_message_id, content=full_response
                            )
                    await store.update_last_message_content_in_redis(redis_key, full_response)

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

                # 最后一次同步，不受节流窗口影响——保证拿到完整的最终文本和
                # 最终 citations 列表（citations 只在流式结束后才完整可知）。
                if assistant_message_id:
                    async with async_session_maker() as final_db:
                        await store.update_message_content(
                            final_db,
                            message_id=assistant_message_id,
                            content=full_response,
                            citations=citations,
                        )
                await store.update_last_message_content_in_redis(redis_key, full_response, citations=citations)

                if conversation_row_id:
                    # best-effort 结构化摘要刷新——只有当满一个窗口的消息
                    # 滑出历史范围时才会真正重新生成（见 P2），大多数时候
                    # 是空操作。
                    background_tasks.add_task(
                        maybe_generate_summary,
                        "report",
                        conversation_row_id,
                        window_size=MAX_HISTORY_MESSAGES,
                    )

            elif event_type == "error":
                payload = json.dumps({"message": event.get("message", "未知错误")}, ensure_ascii=False)
                yield f"event: error\ndata: {payload}\n\n"
                return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        # 这里是手动构造 StreamingResponse，FastAPI 不会像处理普通返回值那样
        # 自动挂载注入的 background_tasks——必须显式传入，否则上面注册的
        # add_task（例如摘要刷新）根本不会被执行。
        background=background_tasks,
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
    返回某份报告的会话历史。
    优先尝试 Redis 热层，未命中则回退到 PostgreSQL。
    """
    owner_key = store.require_owner_key(identity)
    db_user_id = identity.user.id if identity.user else None
    db_anonymous_id = identity.anonymous_id if not identity.user else None
    redis_key = store.history_key(_NAMESPACE, report_id, owner_key)

    if report_id == "demo-report":
        messages = await store.load_history_from_redis(redis_key)
    else:
        result = await db.execute(
            select(Report).where(Report.id == report_id, Report.deleted_at.is_(None))
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="报告不存在")

        # 先尝试热层
        messages = await store.load_history_from_redis(redis_key)

        if not messages:
            # 回退到 DB 并回填 Redis——和 POST /chat 共用同一个回源实现
            # （store.hydrate_history_from_db），只读访问也会预热热层，不再
            # 是"只有发过消息的会话才会被回填"。读的是追加式的
            # conversation_messages 表，不是已废弃的 messages_json 列（见
            # P2 切换，docs/memory-architecture.md §六 P2）。
            conv_result = await db.execute(
                select(ReportConversation).where(
                    ReportConversation.report_id == report_id,
                    *_db_owner_filter(db_user_id, db_anonymous_id),
                )
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                messages = await store.hydrate_history_from_db(
                    db, redis_key, parent_kind="report", parent_id=conv.id
                )

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
    """同时清空 Redis 和 PostgreSQL 中的会话历史。"""
    owner_key = store.require_owner_key(identity)
    db_user_id = identity.user.id if identity.user else None
    db_anonymous_id = identity.anonymous_id if not identity.user else None

    await store.delete_history_from_redis(store.history_key(_NAMESPACE, report_id, owner_key))

    if report_id != "demo-report":
        result = await db.execute(
            select(Report).where(Report.id == report_id, Report.deleted_at.is_(None))
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="报告不存在")

        # 清空 DB
        conv_result = await db.execute(
            select(ReportConversation).where(
                ReportConversation.report_id == report_id,
                *_db_owner_filter(db_user_id, db_anonymous_id),
            )
        )
        conv = conv_result.scalar_one_or_none()
        if conv:
            conv.updated_at = datetime.now(UTC)
            # 消息内容存在 ConversationMessage 里——清空那边的记录
            # （见 docs/memory-architecture.md §六 P2）。
            await db.execute(
                delete(ConversationMessage).where(
                    ConversationMessage.report_conversation_id == conv.id
                )
            )
            await db.commit()
