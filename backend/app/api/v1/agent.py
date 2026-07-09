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
    Create an AgentRun, enqueue it to ARQ for background execution.
    Uses thread_id as idempotency key (see PRD 13.2).
    """
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if not arq_pool:
        raise HTTPException(status_code=503, detail="ARQ pool unavailable")

    thread_id = body.thread_id or str(uuid4())

    # Idempotency check: same thread_id within 24h with active status → 409
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

    # Enqueue to ARQ worker
    await arq_pool.enqueue_job("run_agent", run_id)

    return AgentRunOut(
        run_id=run_id,
        status="queued",
        stream_url=f"/api/v1/agent/runs/{run_id}/events",
    )


@router.get("/runs/{run_id}", response_model=AgentRunStatus)
async def get_agent_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return the current status of an AgentRun."""
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
    SSE endpoint that streams events from Redis Stream key=sse:{run_id}.
    Auth: HttpOnly Cookie session_token is validated by BFF before reaching here.
    See PRD 5.3 for SSE auth strategy.
    """

    async def event_generator():
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        stream_key = f"sse:{run_id}"
        last_id = "0"

        try:
            # Send initial connection confirmation
            yield f"event: connected\ndata: {json.dumps({'run_id': run_id})}\n\n"

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Read from Redis Stream with 2s block timeout
                messages = await redis_client.xread(
                    {stream_key: last_id}, block=2000, count=10
                )

                if messages:
                    for _stream, entries in messages:
                        for entry_id, fields in entries:
                            last_id = entry_id
                            event_type = fields.get("event", "message")
                            data = fields.get("data", "{}")
                            yield f"event: {event_type}\ndata: {data}\n\n"

                            # Stop streaming after completed or failed event
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
