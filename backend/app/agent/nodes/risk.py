"""
Risk Agent node (M2): runs risk engine checks on scored_candidates.
"""
from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.agent.state import VolunteerPlanState
from app.config import settings

logger = logging.getLogger(__name__)


async def _push_sse(run_id: str, event: str, data: dict) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.xadd(
            f"sse:{run_id}",
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
        )
        await redis_client.expire(f"sse:{run_id}", 3600)
    finally:
        await redis_client.aclose()


def _run_risk_sync(scored_candidates: list[dict], rejected_majors: list[str]) -> tuple[list[dict], str]:
    from app.engine.risk_engine import run_all_checks
    return run_all_checks(scored_candidates, rejected_majors)


async def risk_node(state: VolunteerPlanState) -> dict:
    run_id = state["run_id"]
    scored_candidates = state.get("scored_candidates") or []
    profile = state.get("profile") or {}
    rejected_majors: list[str] = profile.get("rejected_majors") or []

    await _push_sse(run_id, "node_started", {"node": "risk", "message": "正在进行风险体检"})

    try:
        risk_items, overall_risk_level = await asyncio.to_thread(
            _run_risk_sync, scored_candidates, rejected_majors
        )
    except Exception as exc:
        logger.exception("risk_node failed")
        risk_items = []
        overall_risk_level = "medium"

    for item in risk_items:
        if item.get("severity") in ("high", "medium"):
            await _push_sse(run_id, "risk_found", {
                "risk_type": item.get("risk_type", ""),
                "severity": item.get("severity", ""),
                "message": item.get("message", ""),
            })

    return {
        "risk_items": risk_items,
        "overall_risk_level": overall_risk_level,
        "needs_human_review": overall_risk_level == "high",
        "review_reasons": (
            [f"风险等级高，需人工复核：{risk_items[0]['message']}"] if overall_risk_level == "high" and risk_items else []
        ),
    }
