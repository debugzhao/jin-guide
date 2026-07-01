"""
Recommendation Agent node (M2): deterministic scoring + three-plan generation.
Runs after the parallel fan-in of retrieval_agent + policy_rule_agent.
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


def _score_all_sync(
    profile: dict,
    hard_blocked_items: list[str],
    max_candidates: int = 200,
) -> tuple[list[dict], dict]:
    """Score all eligible universities and return (scored_candidates, tier_summary)."""
    from app.database import SyncSessionLocal
    from app.engine.scoring import (
        assign_tier,
        compute_admission_score,
        compute_city_family_score,
        compute_major_fit_score,
        compute_cost_risk_score,
        compute_overall_score,
    )
    from app.models.admission import AdmissionScore, University
    from sqlalchemy import select

    province = profile.get("province", "")
    batch = profile.get("batch", "本科批")
    subject_type = profile.get("subject_type", "physics")
    student_rank = profile.get("rank", 0)
    student_subjects = profile.get("subjects", [])
    major_prefs = profile.get("major_prefs") or []
    city_prefs = profile.get("city_prefs") or []
    rejected_majors = profile.get("rejected_majors") or []
    home_province = province
    family_budget = profile.get("family_budget")

    # Build set of hard-blocked university IDs from rule engine
    blocked_univ_ids: set[str] = set()
    blocked_subject_combos: set[tuple[str, str]] = set()
    for item in hard_blocked_items:
        if item.startswith("budget:"):
            blocked_univ_ids.add(item.split(":", 1)[1])
        elif item.startswith("subject:"):
            parts = item.split(":", 2)
            if len(parts) == 3:
                blocked_subject_combos.add((parts[1], parts[2]))

    with SyncSessionLocal() as db:
        # Get distinct universities with admission data for this province/batch/subject_type
        rows = db.execute(
            select(
                University.id,
                University.name,
                University.city,
                University.province.label("univ_province"),
                University.is_985,
                University.is_211,
                University.annual_tuition_min,
                University.annual_tuition_max,
            )
            .join(AdmissionScore, AdmissionScore.university_id == University.id)
            .where(
                AdmissionScore.province == province,
                AdmissionScore.batch == batch,
                AdmissionScore.subject_type == subject_type,
            )
            .distinct()
            .limit(max_candidates)
        ).all()

        scored: list[dict] = []
        for row in rows:
            univ_id = row.id
            if univ_id in blocked_univ_ids:
                continue

            # Compute admission score + rank_gap + tier
            try:
                adm_score, rank_gap, tier = compute_admission_score(
                    student_rank=student_rank,
                    university_id=univ_id,
                    province=province,
                    batch=batch,
                    subject_type=subject_type,
                    db=db,
                )
            except Exception:
                adm_score, rank_gap, tier = 50.0, 0.0, "target"

            tuition = row.annual_tuition_max or row.annual_tuition_min or 6000

            major_fit = compute_major_fit_score(
                preference_majors=major_prefs,
                rejected_majors=rejected_majors,
                major_name="",  # no per-major data in M2, use placeholder
                student_subjects=student_subjects,
                required_subjects=[],
            )

            city_score = compute_city_family_score(
                university_city=row.city or "",
                university_province=row.univ_province or "",
                preference_cities=city_prefs,
                home_province=home_province,
                family_budget_per_year=family_budget,
                annual_tuition=tuition,
            )

            cost_risk = compute_cost_risk_score([])

            overall = compute_overall_score(adm_score, major_fit, city_score, cost_risk)

            label_parts = []
            if row.is_985:
                label_parts.append("985")
            if row.is_211:
                label_parts.append("211")

            scored.append({
                "id": f"cand_{univ_id}",
                "university_id": univ_id,
                "university_name": row.name,
                "university_city": row.city or "",
                "province": row.univ_province or "",
                "major_group": "",
                "major_name": major_prefs[0] if major_prefs else "综合",
                "tier": tier,
                "rank_gap": round(rank_gap, 0),
                "probability": round(max(0.1, min(0.99, 0.5 + rank_gap / 30000)), 2),
                "admission_safety_score": round(adm_score, 1),
                "overall_score": round(overall, 1),
                "tuition_per_year": tuition,
                "subject_requirements": [],
                "rank_reference": {"province": province, "batch": batch},
                "recommendation_reasons": [],
                "risk_items": [],
                "evidence_ids": [],
                "tags": label_parts,
            })

    # Sort by overall_score descending
    scored.sort(key=lambda c: c["overall_score"], reverse=True)

    tier_summary = {
        t: sum(1 for c in scored if c["tier"] == t)
        for t in ("high_rush", "rush", "target", "safe")
    }
    return scored, tier_summary


async def recommendation_agent(state: VolunteerPlanState) -> dict:
    run_id = state["run_id"]
    profile = state.get("profile") or {}
    hard_blocked_items = state.get("hard_blocked_items") or []

    await _push_sse(run_id, "node_started", {"node": "recommendation", "message": "正在生成候选志愿方案"})

    try:
        scored_candidates, tier_summary = await asyncio.to_thread(
            _score_all_sync, profile, hard_blocked_items
        )
    except Exception as exc:
        logger.exception("recommendation_agent scoring failed")
        scored_candidates = []
        tier_summary = {"high_rush": 0, "rush": 0, "target": 0, "safe": 0}

    # Generate three plans from scored candidates
    try:
        from app.engine.planner import generate_plans

        plans = generate_plans(scored_candidates)
    except Exception as exc:
        logger.exception("generate_plans failed")
        plans = {}

    await _push_sse(run_id, "candidates_ready", {
        "total": len(scored_candidates),
        "rush": tier_summary.get("rush", 0),
        "target": tier_summary.get("target", 0),
        "safe": tier_summary.get("safe", 0),
        "plans_generated": len(plans),
    })

    return {
        "candidates": scored_candidates,
        "scored_candidates": scored_candidates,
        "tier_summary": tier_summary,
        # Store plans in report_draft for report_agent to use
        "report_draft": {"plans_raw": plans} if plans else None,
    }
