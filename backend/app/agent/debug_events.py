"""
Debug event emitter for Admin Debug Console.

Usage in LangGraph nodes:
    from app.agent.debug_events import emit_debug_event
    await emit_debug_event(run_id, "node_started", {"node": "retrieval_agent"})

Design:
- Debug events are written to the same Redis Stream as SSE user events (key: sse:{run_id})
  but with a "debug:" prefix on the event type so user-facing SSE endpoints can filter them.
- Admin SSE endpoint reads ALL events including debug: ones.
- try/except swallows all errors — debug emission must never break the main Agent flow.
- No PII in debug payloads.
"""
from __future__ import annotations

import json
import time

import redis.asyncio as aioredis

from app.config import settings

# All known debug event types (informational reference)
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
    Write a debug event to the Redis Stream for this run.

    The event is stored with field "event" = "debug:{event_type}" so the
    user-facing SSE generator can skip it via a simple prefix check.

    Args:
        run_id: The AgentRun ID.
        event_type: One of DEBUG_EVENT_TYPES.
        data: Arbitrary dict. Must NOT contain PII.
        ts: Optional unix timestamp (float). Defaults to now.
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
        # Keep stream alive for 2 hours (same as user events)
        await redis_client.expire(stream_key, 7200)
    except Exception:
        # Debug emission is best-effort — never propagate errors into the Agent
        pass
    finally:
        await redis_client.aclose()
