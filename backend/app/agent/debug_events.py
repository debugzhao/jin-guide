"""
Admin Debug Console 用的调试事件发射器。

在 LangGraph 节点里的用法：
    from app.agent.debug_events import emit_debug_event
    await emit_debug_event(run_id, "node_started", {"node": "retrieval_agent"})

设计要点：
- 调试事件写入与用户侧 SSE 事件相同的 Redis Stream（key: sse:{run_id}），
  只是事件类型多加一个 "debug:" 前缀，方便用户侧 SSE 端点按前缀过滤掉它们。
- Admin SSE 端点会读取全部事件，包括带 debug: 前缀的。
- try/except 吞掉所有异常 —— 调试事件发送绝不能打断主 Agent 流程。
- 调试 payload 中不允许出现 PII。
"""
from __future__ import annotations

import json
import time

import redis.asyncio as aioredis

from app.config import settings

# 所有已知的调试事件类型（仅作参考说明）
DEBUG_EVENT_TYPES = frozenset(
    [
        "node_started",
        "node_completed",
        "tool_called",
        "degraded",
        "circuit_breaker",
        "parallel_fan_out",
        "parallel_fan_in",
        "reflection_iteration",
        "state_checkpoint",
        "stream_end",
    ]
)


async def emit_debug_event(
    run_id: str,
    event_type: str,
    data: dict,
    *,
    ts: float | None = None,
) -> None:
    """
    向本次 run 对应的 Redis Stream 写入一条调试事件。

    事件以 "event" = "debug:{event_type}" 字段存储，这样用户侧的 SSE
    生成器只需做一次简单的前缀判断就能跳过它。

    Args:
        run_id: AgentRun 的 ID。
        event_type: DEBUG_EVENT_TYPES 中的某一个取值。
        data: 任意字典，但不能包含 PII。
        ts: 可选的 unix 时间戳（float）。默认为当前时间。
    """
    if not run_id:
        return

    payload = {**data, "run_id": run_id, "ts": ts or time.time()}

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        stream_key = f"sse:{run_id}"
        await redis_client.xadd(
            stream_key,
            {
                "event": f"debug:{event_type}",
                "data": json.dumps(payload, ensure_ascii=False, default=str),
            },
        )
        # Stream 保留 7 天（与 Admin Debug console 的回放窗口对齐）
        await redis_client.expire(stream_key, 604800)
    except Exception:
        # 调试事件发送是 best-effort —— 绝不能把异常传播到 Agent 主流程
        pass
    finally:
        await redis_client.aclose()


# ── 针对常见调试事件形态的便捷封装 ─────────────────────────

async def emit_tool_called(
    run_id: str,
    node: str,
    tool: str,
    status: str,
    latency_ms: float,
    **extra,
) -> None:
    """记录一次工具调用（vector_search、cohere_rerank、规则校验等）。"""
    await emit_debug_event(
        run_id,
        "tool_called",
        {"node": node, "tool": tool, "status": status, "latency_ms": latency_ms, **extra},
    )


async def emit_circuit_breaker(run_id: str, node: str, tool: str, state: str, **extra) -> None:
    """记录一次 CircuitBreaker 状态迁移（CLOSED/OPEN/HALF_OPEN）。"""
    await emit_debug_event(
        run_id,
        "circuit_breaker",
        {"node": node, "tool": tool, "state": state, **extra},
    )


async def emit_degraded(run_id: str, node: str, from_tool: str, to_tool: str, reason: str) -> None:
    """记录一次优雅降级回退（例如 vector_search → sql_search）。"""
    await emit_debug_event(
        run_id,
        "degraded",
        {"node": node, "from": from_tool, "to": to_tool, "reason": reason},
    )
