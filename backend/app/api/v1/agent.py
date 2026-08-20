import json
from typing import Optional
from uuid import uuid4

import redis.asyncio as aioredis
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.agent_run import AgentRun

router = APIRouter()


class AgentRunIn(BaseModel):
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    profile_id: Optional[str] = None
    task_type: str = "generate_report"
    input: Optional[dict] = None


class AgentRunOut(BaseModel):
    run_id: str
    status: str
    stream_url: str


class AgentRunStatus(BaseModel):
    run_id: str
    thread_id: str
    status: str
    task_type: str
    cost_tokens: int
    cost_usd: float
    trace_url: Optional[str]
    error_msg: Optional[str]
    created_at: str
    completed_at: Optional[str]


@router.post("/runs", response_model=AgentRunOut, status_code=201)
async def create_agent_run(
    body: AgentRunIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    创建一条 AgentRun，投入 ARQ 队列后台执行。
    用 thread_id 作幂等键（见 PRD 13.2）。
    """
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if not arq_pool:
        raise HTTPException(status_code=503, detail="ARQ pool unavailable")

    thread_id = body.thread_id or str(uuid4())

    # 幂等性检查：24h 内同一 thread_id 存在活跃状态的 run → 409
    existing = await db.execute(
        select(AgentRun).where(
            AgentRun.thread_id == thread_id,
            AgentRun.status.in_(["queued", "running"]),
        )
    )
    existing_run = existing.scalar_one_or_none()
    if existing_run:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "conflict",
                    "message": "该 thread_id 已有活跃的 run",
                    "run_id": existing_run.id,
                }
            },
        )

    run_id = str(uuid4())
    run = AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id=body.user_id,
        anonymous_id=body.anonymous_id,
        profile_id=body.profile_id,
        task_type=body.task_type,
        status="queued",
    )
    db.add(run)
    await db.commit()

    # 投入 ARQ worker 队列
    await arq_pool.enqueue_job("run_agent", run_id)

    return AgentRunOut(
        run_id=run_id,
        status="queued",
        stream_url=f"/api/v1/agent/runs/{run_id}/events",
    )


@router.post("/runs/{run_id}/retry", response_model=AgentRunOut)
async def retry_agent_run(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    显式的完全重启：丢弃这次 run 的 LangGraph checkpoint，从头重新调用图，
    即便 checkpoint 可能还存在。这与 run_agent 默认的重新入队行为（从
    checkpoint 恢复）故意区分开——见 docs/memory-architecture.md §六 P1
    Resume/Retry/Refine 语义。只允许对未产出报告就停止的 run（failed/
    timeout/interrupted）使用；已完成的 run 应该走 /refine 修订，而不是重启。
    """
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if not arq_pool:
        raise HTTPException(status_code=503, detail="ARQ pool unavailable")

    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    if run.status not in ("failed", "timeout", "interrupted"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "conflict",
                    "message": f"run 当前状态为 {run.status}，只有 failed/timeout/interrupted 才能重试",
                }
            },
        )

    run.status = "queued"
    await db.commit()

    await arq_pool.enqueue_job("run_agent", run_id, force_restart=True)

    return AgentRunOut(
        run_id=run.id,
        status="queued",
        stream_url=f"/api/v1/agent/runs/{run.id}/events",
    )


@router.get("/runs/{run_id}", response_model=AgentRunStatus)
async def get_agent_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """返回某个 AgentRun 的当前状态。"""
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    return AgentRunStatus(
        run_id=run.id,
        thread_id=run.thread_id,
        status=run.status,
        task_type=run.task_type,
        cost_tokens=run.cost_tokens,
        cost_usd=run.cost_usd,
        trace_url=run.trace_url,
        error_msg=run.error_msg,
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
):
    """
    SSE 端点，从 Redis Stream（key=sse:{run_id}）读取并转发事件流。
    鉴权：HttpOnly Cookie session_token 在到达这里之前已由 BFF 校验过。
    SSE 鉴权方案详见 PRD 5.3。
    """

    async def event_generator():
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        stream_key = f"sse:{run_id}"
        last_id = "0"

        try:
            # 发送初始连接确认
            yield f"event: connected\ndata: {json.dumps({'run_id': run_id})}\n\n"

            while True:
                # 检查客户端是否已断开
                if await request.is_disconnected():
                    break

                # 从 Redis Stream 读取，阻塞超时 2 秒
                messages = await redis_client.xread(
                    {stream_key: last_id}, block=2000, count=10
                )

                if messages:
                    for _stream, entries in messages:
                        for entry_id, fields in entries:
                            last_id = entry_id
                            event_type = fields.get("event", "message")
                            data = fields.get("data", "{}")

                            # debug: 前缀事件只给 Admin Debug Console（见 admin.py
                            # /admin/runs/{id}/debug-events），用户侧白名单事件（见
                            # docs/backend-prd-v2.md §5.7）都不带这个前缀，跳过转发。
                            if event_type.startswith("debug:"):
                                continue

                            yield f"event: {event_type}\ndata: {data}\n\n"

                            # 遇到 completed 或 failed 事件后停止流式推送
                            if event_type in ("completed", "failed", "error"):
                                return

        except Exception as e:
            error_payload = json.dumps(
                {"event": "error", "message": str(e), "severity": "error"}
            )
            yield f"event: error\ndata: {error_payload}\n\n"
        finally:
            await redis_client.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
