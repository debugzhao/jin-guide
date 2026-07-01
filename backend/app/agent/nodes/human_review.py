"""
Human Review interrupt node (Day 8).

This is NOT a persistent LLM Agent — it runs once, generates a review draft,
creates a HumanReview DB record, pushes an SSE human_interrupt event, then
calls interrupt() to pause graph execution.

When the reviewer submits their conclusion via PATCH /api/v1/reviews/{id},
the resume endpoint enqueues a new ARQ job that calls graph.ainvoke with
Command(resume=payload) + same thread_id config, resuming from here.

PRD reference: Section 11.2 (interrupt mechanism), 11.5 (checklist_json structure).
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx

from app.agent.state import VolunteerPlanState
from app.config import settings

logger = logging.getLogger(__name__)

_REVIEW_MODEL = "report-agent"
_LLM_TIMEOUT = 30.0
_REVIEW_SLA_HOURS = 4


async def _push_sse(run_id: str, event: str, data: dict) -> None:
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.xadd(
            f"sse:{run_id}",
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
        )
        await redis_client.expire(f"sse:{run_id}", 3600)
    finally:
        await redis_client.aclose()


async def _render_review_draft(state: VolunteerPlanState) -> dict:
    """
    Generate checklist_json for the reviewer via LLM.
    Falls back to a rule-based draft if LLM is unavailable.
    """
    risk_items = state.get("risk_items") or []
    compliance_issues = state.get("compliance_issues") or []
    review_reasons = state.get("review_reasons") or []
    data_warnings = state.get("data_warnings") or []
    profile = state.get("profile") or {}
    rank = profile.get("rank", 0)
    iterations = state.get("reflection_iterations", 0)

    # Build trigger reasons
    trigger_reasons: list[str] = []
    if compliance_issues:
        trigger_reasons.append("compliance_failed")
    if iterations >= 3:
        trigger_reasons.append("reflection_max_iterations")
    for r in risk_items:
        if r.get("severity") == "high":
            trigger_reasons.append(r.get("risk_type", "high_risk"))
            break
    if state.get("needs_human_review") and not trigger_reasons:
        trigger_reasons.append("risk_engine_flag")

    # Try LLM to generate natural language summary and checklist items
    try:
        summary_context = (
            f"学生位次 {rank}，"
            f"反思迭代 {iterations} 轮，"
            f"触发原因：{', '.join(trigger_reasons) or '风险引擎标记'}。"
            f"风险项：{len(risk_items)} 条。"
            f"合规问题：{compliance_issues[:3]}。"
        )

        system_msg = (
            "你是高考志愿报告复核系统。根据提供的信息，生成一份简洁的复核底稿，"
            "包含摘要和复核清单。"
            "只返回 JSON，格式：\n"
            '{"summary": "简洁摘要（1-2句）", '
            '"reviewer_checklist": ['
            '{"id": "c1", "item": "检查项描述", "required": true}, ...]}'
        )
        user_msg = f"复核触发背景：{summary_context}"

        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.litellm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.litellm_master_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _REVIEW_MODEL,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 600,
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        llm_data = json.loads(content)
        summary = str(llm_data.get("summary", summary_context))
        reviewer_checklist = llm_data.get("reviewer_checklist") or []

    except Exception as exc:
        logger.warning("LLM draft generation failed in human_review_node: %s", exc)
        # Rule-based fallback
        summary = (
            f"学生位次 {rank}，"
            f"Reflection Agent {iterations} 轮后触发强制复核，"
            f"触发原因：{', '.join(trigger_reasons) or '风险标记'}"
        )
        reviewer_checklist = [
            {"id": "c1", "item": "保底志愿数量是否充足（建议 >= 3 所）", "required": True},
            {"id": "c2", "item": "合规问题是否为误报或已在文案中修正", "required": True},
            {"id": "c3", "item": "数据警告是否影响报告可信度", "required": False},
        ]

    return {
        "summary": summary,
        "trigger_reasons": trigger_reasons,
        "risk_items": [
            {
                "risk_type": r.get("risk_type", ""),
                "severity": r.get("severity", "medium"),
                "targets": r.get("targets", []),
                "message": r.get("message", ""),
            }
            for r in risk_items
        ],
        "compliance_issues": compliance_issues,
        "data_warnings": data_warnings,
        "reviewer_checklist": reviewer_checklist,
    }


async def _create_review_record(
    state: VolunteerPlanState,
    checklist_json: dict,
    review_id: str,
) -> None:
    """Persist HumanReview record to DB."""
    from app.database import async_session_maker
    from app.models.review import HumanReview

    now = datetime.now(UTC)
    timeout_at = now + timedelta(hours=_REVIEW_SLA_HOURS)

    async with async_session_maker() as db:
        record = HumanReview(
            id=review_id,
            report_id=state.get("report_id"),
            run_id=state.get("run_id"),
            status="pending",
            checklist_json=checklist_json,
            timeout_at=timeout_at,
        )
        db.add(record)
        await db.commit()


async def human_review_node(state: VolunteerPlanState) -> dict:
    """
    Human Review interrupt node.

    1. Generate review draft (LLM-assisted checklist)
    2. Create HumanReview DB record
    3. Push SSE human_interrupt event
    4. Call interrupt() — graph pauses here until resume
    5. After resume: return state update with review_task_id
    """
    from langgraph.types import interrupt

    run_id = state["run_id"]
    review_id = str(uuid4())

    logger.info(
        "human_review_node: creating review %s for run %s", review_id, run_id
    )

    # ── 1. Generate checklist_json ─────────────────────────────────────────
    checklist_json = await _render_review_draft(state)

    # ── 2. Persist to DB ────────────────────────────────────────────────────
    try:
        await _create_review_record(state, checklist_json, review_id)
    except Exception as exc:
        logger.exception("Failed to create HumanReview record: %s", exc)

    # ── 3. Push SSE human_interrupt event ────────────────────────────────────
    await _push_sse(
        run_id,
        "human_interrupt",
        {
            "review_task_id": review_id,
            "message": f"报告需要人工复核，预计等待时间 {_REVIEW_SLA_HOURS} 小时",
            "sla_hours": _REVIEW_SLA_HOURS,
            "trigger_reasons": checklist_json.get("trigger_reasons", []),
        },
    )

    # ── 4. Interrupt — graph pauses here ─────────────────────────────────────
    # The value passed to interrupt() is stored in the checkpoint and returned
    # as the interrupt payload to the caller. Resume injects Command(resume=payload)
    # which becomes the return value of interrupt() when graph resumes.
    resume_payload: Any = interrupt(
        {
            "review_task_id": review_id,
            "run_id": run_id,
            "message": "等待人工复核结论",
        }
    )

    # ── 5. After resume: process review conclusion ────────────────────────────
    review_conclusion = "approved"
    if isinstance(resume_payload, dict):
        review_conclusion = resume_payload.get("review_conclusion", "approved")

    logger.info(
        "human_review_node resumed for review %s, conclusion=%s",
        review_id,
        review_conclusion,
    )

    # Update HumanReview record with conclusion
    try:
        from app.database import async_session_maker
        from app.models.review import HumanReview
        from sqlalchemy import select

        async with async_session_maker() as db:
            result = await db.execute(
                select(HumanReview).where(HumanReview.id == review_id)
            )
            record = result.scalar_one_or_none()
            if record:
                record.status = "reviewed"
                record.conclusion = review_conclusion
                record.completed_at = datetime.now(UTC)
                if isinstance(resume_payload, dict):
                    record.reviewer_notes = resume_payload.get("reviewer_notes")
                await db.commit()
    except Exception as exc:
        logger.warning("Failed to update HumanReview record on resume: %s", exc)

    return {
        "review_task_id": review_id,
        "completed_at": datetime.now(UTC).isoformat(),
    }
