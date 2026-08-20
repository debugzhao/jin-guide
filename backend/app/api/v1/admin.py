"""
Admin Debug Console API — 仅 role=admin 可访问，其余请求返回 401/403。
数据本身不含 PII（省份/位次/分数等），仅暴露耗时/费用/工具调用等运维指标。

Endpoints:
  GET  /admin/runs                   — 列出最近的 agent run 及调试摘要
  GET  /admin/runs/{id}              — 单个 run 的完整调试元数据
  GET  /admin/runs/{id}/debug-events — Admin SSE：完整事件流 + 历史回放
  GET  /admin/metrics/summary        — 实时系统指标快照
"""
from __future__ import annotations

import json
import time
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin_role
from app.config import settings
from app.database import get_db
from app.models.agent_run import AgentRun

router = APIRouter(dependencies=[Depends(require_admin_role)])

_METRICS_WINDOW_SECONDS = 300  # 错误率统计的 5 分钟滚动窗口


# ── 数据结构 ────────────────────────────────────────────────────────────────────

class RunSummary(BaseModel):
    id: str
    status: str
    task_type: str
    profile_id: Optional[str]
    cost_usd: float
    cost_tokens: int
    duration_seconds: Optional[float]
    trace_url: Optional[str]
    error_msg: Optional[str]
    # 快速调试指标
    degraded_agents: list[str]
    triggered_human_review: bool
    node_count_completed: int
    created_at: str
    completed_at: Optional[str]


class RunDetail(BaseModel):
    id: str
    thread_id: str
    status: str
    task_type: str
    profile_id: Optional[str]
    cost_usd: float
    cost_tokens: int
    duration_seconds: Optional[float]
    trace_url: Optional[str]
    error_msg: Optional[str]
    debug_summary_json: Optional[dict]
    created_at: str
    completed_at: Optional[str]


class MetricsSummary(BaseModel):
    total_runs_24h: int
    completed_runs_24h: int
    failed_runs_24h: int
    error_rate_pct: float
    avg_duration_seconds: Optional[float]
    total_cost_usd_24h: float
    active_runs: int
    timestamp: float


# ── 辅助函数 ────────────────────────────────────────────────────────────────────

def _extract_debug_summary(run: AgentRun) -> dict:
    """返回 debug_summary_json，缺失时给一个最小兜底结构。"""
    if run.debug_summary_json:
        return run.debug_summary_json
    return {
        "node_timings": {},
        "tool_call_summary": [],
        "state_summary": {},
        "cost_breakdown": {
            "cost_usd": run.cost_usd,
            "cost_tokens": run.cost_tokens,
        },
    }


def _get_degraded_agents(run: AgentRun) -> list[str]:
    summary = run.debug_summary_json or {}
    return summary.get("degraded_agents", [])


# ── 接口 ──────────────────────────────────────────────────────────────────────

@router.get("/runs", response_model=list[RunSummary])
async def list_admin_runs(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="按状态过滤"),
    db: AsyncSession = Depends(get_db),
):
    """
    返回最近的 agent run 列表，附带轻量调试指标。
    不含 PII——档案数据不在返回范围内。
    """
    stmt = select(AgentRun).order_by(desc(AgentRun.created_at)).limit(limit)
    if status:
        stmt = stmt.where(AgentRun.status == status)

    result = await db.execute(stmt)
    runs = result.scalars().all()

    summaries = []
    for run in runs:
        debug = run.debug_summary_json or {}
        summaries.append(
            RunSummary(
                id=run.id,
                status=run.status,
                task_type=run.task_type,
                profile_id=run.profile_id,
                cost_usd=run.cost_usd or 0.0,
                cost_tokens=run.cost_tokens or 0,
                duration_seconds=run.duration_seconds,
                trace_url=run.trace_url,
                error_msg=run.error_msg,
                degraded_agents=debug.get("degraded_agents", []),
                triggered_human_review=debug.get("triggered_human_review", False),
                node_count_completed=len(debug.get("node_timings", {})),
                created_at=run.created_at.isoformat(),
                completed_at=run.completed_at.isoformat() if run.completed_at else None,
            )
        )
    return summaries


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_admin_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """返回单个 run 的完整调试元数据。"""
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    return RunDetail(
        id=run.id,
        thread_id=run.thread_id,
        status=run.status,
        task_type=run.task_type,
        profile_id=run.profile_id,
        cost_usd=run.cost_usd or 0.0,
        cost_tokens=run.cost_tokens or 0,
        duration_seconds=run.duration_seconds,
        trace_url=run.trace_url,
        error_msg=run.error_msg,
        debug_summary_json=_extract_debug_summary(run),
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.get("/runs/{run_id}/debug-events")
async def stream_debug_events(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin Debug SSE 端点。从 Redis Stream 起点（0-0）回放完整事件历史，
    若 run 仍在进行中则继续接续实时流。

    run 完成/失败或客户端断开连接时，以 stream_end 事件结束。
    """
    # 校验 run 是否存在
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    is_finished = run.status in ("completed", "failed", "timeout")

    async def event_generator():
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        stream_key = f"sse:{run_id}"
        last_id = "0"  # 从最开头开始，用于历史回放

        try:
            yield f"data: {json.dumps({'event': 'connected', 'run_id': run_id, 'replay': True})}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                # 读取所有事件（包括 debug: 前缀的）
                messages = await redis_client.xread(
                    {stream_key: last_id}, block=2000, count=50
                )

                if messages:
                    for _stream, entries in messages:
                        for entry_id, fields in entries:
                            last_id = entry_id
                            event_type = fields.get("event", "message")
                            data = fields.get("data", "{}")
                            # 把 debug: 前缀规整成前端能识别的格式
                            yield f"event: {event_type}\ndata: {data}\n\n"

                elif is_finished:
                    # 没有更多事件且 run 已结束——发送终止事件
                    yield f"event: debug:stream_end\ndata: {json.dumps({'run_id': run_id, 'ts': time.time()})}\n\n"
                    break

        except Exception as exc:
            error_payload = json.dumps({"event": "error", "message": str(exc)})
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


@router.get("/metrics/summary", response_model=MetricsSummary)
async def get_metrics_summary(
    db: AsyncSession = Depends(get_db),
):
    """
    返回实时系统指标快照。
    24 小时计数从 PostgreSQL 聚合而来；活跃 run 数同样查自 DB。
    """
    from datetime import timedelta
    from datetime import UTC, datetime
    from sqlalchemy import func

    now = datetime.now(UTC)
    since_24h = now - timedelta(hours=24)

    # 近 24 小时总 run 数
    total_result = await db.execute(
        select(func.count(AgentRun.id)).where(AgentRun.created_at >= since_24h)
    )
    total_runs = total_result.scalar_one() or 0

    # 近 24 小时已完成的 run 数
    completed_result = await db.execute(
        select(func.count(AgentRun.id)).where(
            AgentRun.created_at >= since_24h,
            AgentRun.status == "completed",
        )
    )
    completed_runs = completed_result.scalar_one() or 0

    # 近 24 小时失败的 run 数
    failed_result = await db.execute(
        select(func.count(AgentRun.id)).where(
            AgentRun.created_at >= since_24h,
            AgentRun.status == "failed",
        )
    )
    failed_runs = failed_result.scalar_one() or 0

    # 已完成 run 的平均耗时
    avg_result = await db.execute(
        select(func.avg(AgentRun.duration_seconds)).where(
            AgentRun.created_at >= since_24h,
            AgentRun.status == "completed",
            AgentRun.duration_seconds.is_not(None),
        )
    )
    avg_duration = avg_result.scalar_one()

    # 总费用
    cost_result = await db.execute(
        select(func.sum(AgentRun.cost_usd)).where(AgentRun.created_at >= since_24h)
    )
    total_cost = cost_result.scalar_one() or 0.0

    # 活跃 run 数
    active_result = await db.execute(
        select(func.count(AgentRun.id)).where(
            AgentRun.status.in_(["queued", "running"])
        )
    )
    active_runs = active_result.scalar_one() or 0

    error_rate = (failed_runs / total_runs * 100) if total_runs > 0 else 0.0

    return MetricsSummary(
        total_runs_24h=total_runs,
        completed_runs_24h=completed_runs,
        failed_runs_24h=failed_runs,
        error_rate_pct=round(error_rate, 1),
        avg_duration_seconds=round(float(avg_duration), 1) if avg_duration else None,
        total_cost_usd_24h=round(float(total_cost), 4),
        active_runs=active_runs,
        timestamp=time.time(),
    )
