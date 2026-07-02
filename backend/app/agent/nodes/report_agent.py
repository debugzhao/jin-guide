"""
Report Agent node (M2): LLM generates recommendation reasons,
builds plan_json, compliance check, saves to DB.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import redis.asyncio as aioredis

from app.agent.nodes.compliance import check_compliance_report
from app.agent.state import VolunteerPlanState
from app.config import settings

logger = logging.getLogger(__name__)

_REPORT_MODEL = "report-agent"
_MAX_CANDIDATES_FOR_LLM = 12  # limit to avoid huge prompts
_LLM_TIMEOUT = 60.0


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


async def _call_llm(messages: list[dict]) -> str:
    """Call LiteLLM proxy to generate report text."""
    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
        resp = await client.post(
            f"{settings.litellm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.litellm_master_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _REPORT_MODEL,
                "messages": messages,
                "max_tokens": 2000,
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _build_llm_prompt(profile: dict, top_candidates: list[dict]) -> list[dict]:
    """Build the LLM prompt for generating recommendation reasons."""
    province = profile.get("province", "")
    score = profile.get("score", 0)
    rank = profile.get("rank", 0)
    subjects = profile.get("subjects") or []
    batch = profile.get("batch", "本科批")

    cand_lines = []
    for i, c in enumerate(top_candidates, 1):
        cand_lines.append(
            f"{i}. {c.get('university_name', '')}（{c.get('university_city', '')}）"
            f" - {c.get('major_name', '')} - {c.get('tier', '')}档 - 综合评分{c.get('overall_score', 0)}"
            f" - 预估录取概率{int(c.get('probability', 0)*100)}%"
            f" - 学费{c.get('tuition_per_year', 0):,}元/年"
            + (f" - {'、'.join(c.get('tags', []))}" if c.get('tags') else "")
        )

    candidates_text = "\n".join(cand_lines)

    system_msg = (
        "你是一位专业的高考志愿咨询师。根据学生档案和候选院校信息，"
        "为每所院校生成2-3条具体的推荐理由。"
        "要求：语言简洁、基于数据事实、避免模糊表述。"
        "禁止出现：保证录取、必中、精准录取、包过、保上、百分百录取、内部数据等表述。"
        "只返回JSON格式，不要其他内容。"
    )

    user_msg = f"""学生信息：
- 省份：{province}，批次：{batch}
- 成绩：{score}分，位次：{rank}
- 选科：{'、'.join(subjects)}

候选院校列表（共{len(top_candidates)}所）：
{candidates_text}

请为每所院校生成推荐理由，返回格式：
{{
  "reasons": {{
    "院校序号（1-{len(top_candidates)}）": ["理由1", "理由2", "理由3（可选）"]
  }}
}}"""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _parse_llm_reasons(content: str, candidate_count: int) -> dict[int, list[str]]:
    """Parse LLM response into per-candidate reasons dict."""
    try:
        # Strip markdown code fences if present
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        parsed = json.loads(text)
        reasons_raw = parsed.get("reasons", {})
        result: dict[int, list[str]] = {}
        for k, v in reasons_raw.items():
            try:
                idx = int(str(k).strip())
                if isinstance(v, list):
                    result[idx] = [str(r) for r in v[:3]]
            except (ValueError, TypeError):
                pass
        return result
    except Exception:
        logger.warning("Failed to parse LLM reasons response")
        return {}


def _build_plan_json(
    scored_candidates: list[dict],
    plans_raw: dict,
    risk_items: list[dict],
    profile: dict,
) -> dict:
    """Assemble the final plan_json structure from planner output."""
    risk_level = "low"
    if any(r.get("severity") == "high" for r in risk_items):
        risk_level = "high"
    elif any(r.get("severity") == "medium" for r in risk_items):
        risk_level = "medium"

    risk_items_out = [
        {
            "level": r.get("severity", "low"),
            "description": r.get("message", ""),
        }
        for r in risk_items
    ]

    plan_descriptions = {
        "conservative": "以稳为主，优先确保录取成功率，适合求稳的考生",
        "balanced": "冲稳保均衡分配，综合性价比最高，AI推荐方案",
        "aggressive": "优先冲击高层次院校，适合心态好的考生",
    }

    plans_out = []
    for plan_type, plan_data in plans_raw.items():
        candidates = plan_data.get("volunteers", [])
        plans_out.append({
            "type": plan_type,
            "label": {"conservative": "保守型", "balanced": "均衡型", "aggressive": "进取型"}.get(
                plan_type, plan_type
            ),
            "description": plan_descriptions.get(plan_type, ""),
            "candidates": candidates,
        })

    return {
        "profile_summary": {
            "province": profile.get("province", ""),
            "score": profile.get("score", 0),
            "rank": profile.get("rank", 0),
            "subjects": profile.get("subjects") or [],
        },
        "risk_level": risk_level,
        "risk_items": risk_items_out,
        "plans": plans_out,
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def report_agent(state: VolunteerPlanState) -> dict:
    run_id = state["run_id"]
    profile = state.get("profile") or {}
    scored_candidates = state.get("scored_candidates") or []
    risk_items = state.get("risk_items") or []
    overall_risk = state.get("overall_risk_level", "medium")
    report_draft = state.get("report_draft") or {}
    plans_raw: dict = report_draft.get("plans_raw") or {}

    await _push_sse(run_id, "node_started", {"node": "report", "message": "正在生成三套方案报告"})

    # ── 1. LLM: generate recommendation reasons ──────────────────────────────
    top_candidates = scored_candidates[:_MAX_CANDIDATES_FOR_LLM]
    llm_reasons: dict[int, list[str]] = {}

    if top_candidates:
        try:
            messages = _build_llm_prompt(profile, top_candidates)
            llm_content = await _call_llm(messages)
            llm_reasons = _parse_llm_reasons(llm_content, len(top_candidates))
        except Exception as exc:
            logger.warning("LLM call failed in report_agent: %s", exc)
            # Fallback: generate basic reasons from data
            for i, c in enumerate(top_candidates, 1):
                reasons = []
                tier = c.get("tier", "target")
                rank_gap = c.get("rank_gap", 0)
                if tier in ("rush", "high_rush"):
                    reasons.append(f"冲击目标，位次差 {abs(int(rank_gap))} 名，具有挑战性")
                elif tier == "target":
                    reasons.append(f"历史录取位次稳定，当前位次差 {int(rank_gap)} 名，匹配度高")
                else:
                    reasons.append(f"保底院校，安全边际充足，位次差 {int(rank_gap)} 名")
                if c.get("tags"):
                    reasons.append(f"{'、'.join(c['tags'])}高校，综合实力强劲")
                llm_reasons[i] = reasons

    # Attach LLM reasons to candidates
    enriched_candidates = []
    for i, c in enumerate(scored_candidates, 1):
        c_out = dict(c)
        if i <= _MAX_CANDIDATES_FOR_LLM and i in llm_reasons:
            c_out["recommendation_reasons"] = llm_reasons[i]
        elif not c_out.get("recommendation_reasons"):
            c_out["recommendation_reasons"] = [f"综合评分 {c.get('overall_score', 0)}，{c.get('tier', '')}档位"]
        enriched_candidates.append(c_out)

    # Update plans_raw with enriched candidates (planner uses "volunteers" key)
    if plans_raw:
        univ_to_candidate = {c["university_id"]: c for c in enriched_candidates if "university_id" in c}
        for plan_type, plan_data in plans_raw.items():
            updated_cands = []
            for c in plan_data.get("volunteers", []):
                uid = c.get("university_id", "")
                updated_cands.append(univ_to_candidate.get(uid, c))
            plans_raw[plan_type]["volunteers"] = updated_cands

    # ── 2. Build plan_json ────────────────────────────────────────────────────
    plan_json = _build_plan_json(enriched_candidates, plans_raw, risk_items, profile)

    # ── 3. Compliance check ───────────────────────────────────────────────────
    compliance_passed, compliance_issues = check_compliance_report(plan_json)

    if not compliance_passed:
        logger.warning("Compliance issues found: %s", compliance_issues)

    # ── 4. Compute risk_score (0–100, lower = safer) ─────────────────────────
    risk_penalty = {"high": 70, "medium": 45, "low": 20}
    risk_score = float(risk_penalty.get(overall_risk, 45))

    # ── 5. Persist to DB ──────────────────────────────────────────────────────
    report_id = str(uuid4())
    db_saved = False
    try:
        from app.database import async_session_maker
        from app.models.report import Report

        async with async_session_maker() as db:
            report = Report(
                id=report_id,
                profile_id=state.get("profile_id") or None,
                run_id=run_id,
                status="completed",
                risk_level=overall_risk,
                risk_score=risk_score,
                plan_json=plan_json,
                evidence_json=state.get("evidence_list") or [],
                dataset_version=state.get("dataset_version"),
            )
            db.add(report)
            await db.commit()
            db_saved = True
    except Exception as exc:
        logger.exception("Failed to persist report to DB")
        compliance_issues.append(f"报告保存失败：{exc!s}")

    if db_saved:
        await _push_sse(run_id, "completed", {
            "report_id": report_id,
            "risk_level": overall_risk,
            "compliance_passed": compliance_passed,
        })
    else:
        await _push_sse(run_id, "failed", {
            "message": "报告保存失败，请稍后重试",
        })

    return {
        "report_id": report_id,
        "report_draft": plan_json,
        "compliance_passed": compliance_passed,
        "compliance_issues": compliance_issues,
        "completed_at": datetime.now(UTC).isoformat(),
    }
