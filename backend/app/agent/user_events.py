"""
用户侧协作事件推送 (docs/backend-prd-v2.md §5.7)。

与 debug_events.py 的 `debug:` 前缀事件共用同一条 `sse:{run_id}` Redis Stream，
但不加前缀，供 GET /agent/runs/{id}/events 直接转发给前端渲染"生成过程卡片"。
这里只放白名单里新增的协作事件（agents_parallel_started/merged、self_check_round、
degraded_notice）；node_started/evidence_found/rule_checked/candidates_ready/risk_found
等既有事件仍由各节点文件里的本地 `_push_sse` 直接推送，不经过本模块。
"""
from __future__ import annotations

import json

import redis.asyncio as aioredis

from app.config import settings


async def push_user_event(run_id: str, event: str, data: dict) -> None:
    """
    Best-effort push：失败静默吞掉，绝不能因为一次用户侧事件推送失败而打断主流程
    （与 debug_events.emit_debug_event 的容错策略一致）。
    """
    if not run_id:
        return

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.xadd(
            f"sse:{run_id}",
            {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)},
        )
        await redis_client.expire(f"sse:{run_id}", 604800)
    except Exception:
        pass
    finally:
        await redis_client.aclose()
