"""
Profile Agent node — 档案不完整时的兜底追问 (docs/backend-prd-v2.md §10.1, §10.3)。

正常流程下 `POST /reports/generate` 只在前端确认 profile_complete=true 后才会调用——
对话式建档过程中的矛盾检测/追问由 `POST /profile/field-check`（见 profile.py）承担，
不需要经过 LLM。这个节点是图内的防御性兜底：万一 run 被以不完整档案触发，在这里
把缺口转成一句自然语言追问并结束 run，而不是带着空/低质量数据硬跑完整条 pipeline。
"""
from __future__ import annotations

import json
import logging

import httpx
import redis.asyncio as aioredis

from app.agent.state import VolunteerPlanState
from app.config import settings

logger = logging.getLogger(__name__)

_PROFILE_AGENT_MODEL = "profile-agent"
_LLM_TIMEOUT = 15.0

_REQUIRED_FIELD_LABELS = {
    "province": "省份",
    "rank": "位次",
    "score": "分数",
    "subjects": "选科",
    "batch": "批次",
}


async def _push_sse(run_id: str, event: str, data: dict) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.xadd(
            f"sse:{run_id}",
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
        )
        await redis_client.expire(f"sse:{run_id}", 604800)
    finally:
        await redis_client.aclose()


def _missing_fields(profile: dict) -> list[str]:
    return [label for field, label in _REQUIRED_FIELD_LABELS.items() if not profile.get(field)]


async def _phrase_clarification(missing: list[str]) -> str:
    """把缺失字段列表转成一句自然语言追问；LLM 不可用时用确定性模板兜底。"""
    fallback = f"还差一点信息才能生成报告：{'、'.join(missing)}，麻烦补充一下～"
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.litellm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.litellm_master_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _PROFILE_AGENT_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是高考志愿助手，用一句自然、口语化的中文追问用户补充缺失的建档信息，不要输出多余内容。",
                        },
                        {"role": "user", "content": f"还缺少这些字段：{'、'.join(missing)}"},
                    ],
                    "max_tokens": 100,
                    "temperature": 1,
                },
            )
            resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        return content or fallback
    except Exception as exc:
        logger.warning("profile_agent LLM phrasing failed, using fallback: %s", exc)
        return fallback


async def profile_agent(state: VolunteerPlanState) -> dict:
    run_id = state["run_id"]
    profile = state.get("profile") or {}

    missing = _missing_fields(profile)
    message = await _phrase_clarification(missing) if missing else "档案信息不完整，请补充后重试。"

    await _push_sse(run_id, "profile_incomplete", {"missing_fields": missing, "message": message})

    return {"profile_pending_questions": [message]}
