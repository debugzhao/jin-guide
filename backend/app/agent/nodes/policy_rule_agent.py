"""
Policy Rule Agent node (M2): deterministic rule checks with CircuitBreaker protection.
Runs in parallel with retrieval_agent after data_resolver.
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


def _run_rules_sync(profile: dict, dataset_version: str) -> tuple[list[dict], list[str]]:
    """Run all rule checks synchronously in thread pool."""
    from datetime import datetime

    from app.agent.circuit_breaker import get_circuit_breaker
    from app.database import SyncSessionLocal
    from app.engine.rules import (
        check_batch_eligibility,
        check_budget,
        check_subject_req,
    )
    from app.models.admission import University
    from sqlalchemy import select

    breaker = get_circuit_breaker()
    rule_results: list[dict] = []
    hard_blocked: list[str] = []

    province = profile.get("province", "")
    batch = profile.get("batch", "本科批")
    subject_type = profile.get("subject_type", "physics")
    student_rank = profile.get("rank", 0)
    student_subjects = profile.get("subjects", [])
    family_budget = profile.get("family_budget")
    year = datetime.now().year - 1  # use most recent complete year

    with SyncSessionLocal() as db:
        # ── 1. Batch eligibility ────────────────────────────────────────────
        if not breaker.is_open("rule_batch"):
            try:
                result = check_batch_eligibility(
                    student_rank=student_rank,
                    province=province,
                    target_batch=batch,
                    year=year,
                    subject_type=subject_type,
                    db=db,
                )
                breaker.record_result("rule_batch", result)
                rule_results.append({
                    "rule_type": "batch_eligibility",
                    "target": batch,
                    "status": result.status,
                    "reason": result.text,
                    "data": result.data,
                })
                if result.status == "ERROR":
                    hard_blocked.append(f"batch:{batch}")
            except Exception as exc:
                logger.exception("check_batch_eligibility raised")
                rule_results.append({
                    "rule_type": "batch_eligibility",
                    "target": batch,
                    "status": "PARTIAL",
                    "reason": f"规则引擎异常：{exc!s}",
                    "data": {},
                })
        else:
            rule_results.append({
                "rule_type": "batch_eligibility",
                "target": batch,
                "status": "PARTIAL",
                "reason": "批次校验断路器 OPEN，已跳过",
                "data": {},
            })

        # ── 2. Subject requirements for preferred majors ────────────────────
        major_prefs: list[str] = profile.get("major_prefs") or []
        if major_prefs:
            universities = db.execute(select(University).limit(20)).scalars().all()
            checked_combos: set[tuple[str, str]] = set()

            for major_name in major_prefs[:5]:  # limit to top 5 preferred majors
                for univ in universities[:10]:
                    combo = (univ.id, major_name)
                    if combo in checked_combos:
                        continue
                    checked_combos.add(combo)

                    if breaker.is_open("rule_subject"):
                        rule_results.append({
                            "rule_type": "subject_requirement",
                            "target": f"{univ.name}/{major_name}",
                            "status": "PARTIAL",
                            "reason": "选科校验断路器 OPEN，已跳过",
                            "data": {},
                        })
                        continue

                    try:
                        result = check_subject_req(
                            university_id=univ.id,
                            major_name=major_name,
                            student_subjects=student_subjects,
                            db=db,
                        )
                        breaker.record_result("rule_subject", result)
                        rule_results.append({
                            "rule_type": "subject_requirement",
                            "target": f"{univ.name}/{major_name}",
                            "status": result.status,
                            "reason": result.text,
                            "data": result.data,
                        })
                        if result.status == "ERROR":
                            hard_blocked.append(f"subject:{univ.id}:{major_name}")
                    except Exception as exc:
                        logger.exception("check_subject_req raised")

        # ── 3. Budget check for top universities ───────────────────────────
        if family_budget and family_budget > 0:
            universities = db.execute(
                select(University).where(
                    University.annual_tuition_max.isnot(None)
                ).limit(30)
            ).scalars().all()

            for univ in universities:
                if breaker.is_open("rule_budget"):
                    break
                try:
                    result = check_budget(
                        university_id=univ.id,
                        family_budget_per_year=family_budget,
                        db=db,
                    )
                    breaker.record_result("rule_budget", result)
                    if result.status == "ERROR":
                        hard_blocked.append(f"budget:{univ.id}")
                        rule_results.append({
                            "rule_type": "budget",
                            "target": univ.name,
                            "status": result.status,
                            "reason": result.text,
                            "data": result.data,
                        })
                except Exception as exc:
                    logger.exception("check_budget raised for %s", univ.id)

    return rule_results, hard_blocked


async def policy_rule_agent(state: VolunteerPlanState) -> dict:
    run_id = state["run_id"]
    profile = state.get("profile") or {}

    await _push_sse(run_id, "node_started", {"node": "policy_rule_agent", "message": "正在校验志愿规则"})

    dataset_version = state.get("dataset_version", "")

    try:
        rule_results, hard_blocked = await asyncio.to_thread(
            _run_rules_sync, profile, dataset_version
        )
    except Exception as exc:
        logger.exception("policy_rule_agent failed")
        rule_results = [{
            "rule_type": "error",
            "target": "all",
            "status": "PARTIAL",
            "reason": f"规则引擎异常：{exc!s}",
            "data": {},
        }]
        hard_blocked = []

    # Emit SSE for each result
    for r in rule_results:
        if r["status"] in ("SUCCESS", "ERROR"):
            await _push_sse(run_id, "rule_checked", {
                "rule": r["rule_type"],
                "target": r["target"],
                "status": r["status"],
            })

    await _push_sse(run_id, "node_completed", {
        "node": "policy_rule_agent",
        "rule_count": len(rule_results),
        "hard_blocked": len(hard_blocked),
        "message": f"规则校验完成，{len(hard_blocked)} 项硬阻断",
    })

    return {
        "rule_results": rule_results,
        "hard_blocked_items": hard_blocked,
    }
