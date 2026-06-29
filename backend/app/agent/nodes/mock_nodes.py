"""
Mock implementations of all LangGraph agent nodes for M1.

Each node:
1. Sleeps 1.5s to simulate real processing time
2. Pushes SSE events to Redis Stream key=sse:{run_id}
3. Updates and returns state with hardcoded but realistic data

Real implementations replace these in M2/M3.
"""
import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import redis.asyncio as aioredis

from app.agent.state import VolunteerPlanState
from app.config import settings


async def _push_sse_event(run_id: str, event: str, data: dict) -> None:
    """Push a single SSE event to Redis Stream for the given run_id."""
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        stream_key = f"sse:{run_id}"
        await redis_client.xadd(
            stream_key,
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
        )
        # Auto-expire stream after 1 hour to avoid memory leak
        await redis_client.expire(stream_key, 3600)
    finally:
        await redis_client.aclose()


async def mock_data_resolver(state: VolunteerPlanState) -> dict:
    """
    Mock Data Resolver node.
    Verifies data availability and locks dataset version.
    Real impl: queries documents table for published status.
    """
    run_id = state["run_id"]

    await _push_sse_event(
        run_id,
        "node_started",
        {"node": "data_resolver", "message": "正在确认数据版本"},
    )

    await asyncio.sleep(1.5)

    dataset_version = "henan_2026_v1"

    await _push_sse_event(
        run_id,
        "node_completed",
        {
            "node": "data_resolver",
            "dataset_version": dataset_version,
            "message": "数据版本已锁定",
        },
    )

    return {
        "dataset_version": dataset_version,
        "data_warnings": [],
    }


async def mock_retrieval_and_rules(state: VolunteerPlanState) -> dict:
    """
    Mock combined Retrieval + Policy Rule node (simplified sequential for M1).
    Real impl: runs Retrieval Agent and Policy Rule Agent in parallel via Send API.
    """
    run_id = state["run_id"]

    await _push_sse_event(
        run_id,
        "node_started",
        {"node": "retrieval_and_rules", "message": "正在检索招生数据"},
    )

    await asyncio.sleep(1.5)

    # Mock evidence items
    evidence_list = [
        {
            "source_id": "src_001",
            "source_type": "admission_plan",
            "title": "2026年河南省本科批招生计划",
            "authority_level": "official",
            "year": 2026,
            "province": "河南",
            "batch": "本科批",
            "dataset_version": state.get("dataset_version", "henan_2026_v1"),
            "retrieved_at": datetime.now(UTC).isoformat(),
            "fields": ["major_group", "subjects", "quota", "tuition"],
            "quote": "计算机类专业在河南省2026年招生计划总计划数 1240 人",
        },
        {
            "source_id": "src_002",
            "source_type": "admission_score",
            "title": "2025年河南省本科批历年投档线",
            "authority_level": "official",
            "year": 2025,
            "province": "河南",
            "batch": "本科批",
            "dataset_version": state.get("dataset_version", "henan_2026_v1"),
            "retrieved_at": datetime.now(UTC).isoformat(),
            "fields": ["min_score", "min_rank", "university_id"],
            "quote": "郑州大学计算机专业组2025年最低录取位次 38500",
        },
    ]

    await _push_sse_event(
        run_id,
        "evidence_found",
        {
            "source_id": "src_001",
            "title": "2026年河南省本科批招生计划",
            "authority": "official",
        },
    )

    # Mock rule results
    rule_results = [
        {
            "rule_type": "subject_requirement",
            "target": "计算机科学与技术",
            "status": "passed",
            "reason": "选科物理+化学满足要求",
        },
        {
            "rule_type": "batch_eligibility",
            "target": "本科批",
            "status": "passed",
            "reason": "分数达到本科批线",
        },
    ]

    await _push_sse_event(
        run_id,
        "rule_checked",
        {
            "rule": "subject_requirement",
            "target": "计算机科学与技术",
            "status": "passed",
        },
    )

    return {
        "evidence_list": evidence_list,
        "retrieval_complete": True,
        "rule_results": rule_results,
        "hard_blocked_items": [],
    }


async def mock_recommendation(state: VolunteerPlanState) -> dict:
    """
    Mock Recommendation Engine node.
    Generates 8 scored candidate entries across rush/target/safe tiers.
    Real impl: calls Rule Engine + Recommendation Engine with real DB queries.
    """
    run_id = state["run_id"]

    await _push_sse_event(
        run_id,
        "node_started",
        {"node": "recommendation", "message": "正在生成候选志愿方案"},
    )

    await asyncio.sleep(1.5)

    # 8 mock candidates spanning all tiers
    scored_candidates = [
        {
            "id": "cand_001",
            "university_name": "武汉大学",
            "university_city": "武汉",
            "province": "湖北",
            "major_group": "080901",
            "major_name": "计算机科学与技术",
            "tier": "rush",
            "score_diff": -15,
            "probability": 0.30,
            "admission_safety_score": 35,
            "overall_score": 62.5,
            "tuition_per_year": 5800,
            "subject_requirements": ["物理"],
            "rank_reference": {"year": 2025, "min_rank": 18500},
            "recommendation_reasons": ["985高校，计算机专业实力强", "冲击名校的合理选择"],
            "risk_items": [],
            "evidence_ids": ["src_001", "src_002"],
        },
        {
            "id": "cand_002",
            "university_name": "华中科技大学",
            "university_city": "武汉",
            "province": "湖北",
            "major_group": "080902",
            "major_name": "软件工程",
            "tier": "rush",
            "score_diff": -8,
            "probability": 0.42,
            "admission_safety_score": 45,
            "overall_score": 70.0,
            "tuition_per_year": 5800,
            "subject_requirements": ["物理"],
            "rank_reference": {"year": 2025, "min_rank": 28000},
            "recommendation_reasons": ["985高校，软件工程就业好", "位次差较小，有冲击机会"],
            "risk_items": [],
            "evidence_ids": ["src_001"],
        },
        {
            "id": "cand_003",
            "university_name": "郑州大学",
            "university_city": "郑州",
            "province": "河南",
            "major_group": "060001",
            "major_name": "计算机科学与技术",
            "tier": "target",
            "score_diff": 2500,
            "probability": 0.85,
            "admission_safety_score": 78,
            "overall_score": 82.0,
            "tuition_per_year": 6000,
            "subject_requirements": ["物理", "化学"],
            "rank_reference": {"year": 2025, "min_rank": 38500},
            "recommendation_reasons": ["历年最低位次稳定", "省内211，综合评分高"],
            "risk_items": [],
            "evidence_ids": ["src_001", "src_002"],
        },
        {
            "id": "cand_004",
            "university_name": "河南大学",
            "university_city": "开封",
            "province": "河南",
            "major_group": "060002",
            "major_name": "数据科学与大数据技术",
            "tier": "target",
            "score_diff": 3200,
            "probability": 0.88,
            "admission_safety_score": 82,
            "overall_score": 79.5,
            "tuition_per_year": 5500,
            "subject_requirements": ["物理"],
            "rank_reference": {"year": 2025, "min_rank": 42000},
            "recommendation_reasons": ["省内知名高校", "新兴专业就业前景好"],
            "risk_items": [],
            "evidence_ids": ["src_001"],
        },
        {
            "id": "cand_005",
            "university_name": "河南理工大学",
            "university_city": "焦作",
            "province": "河南",
            "major_group": "070001",
            "major_name": "软件工程",
            "tier": "target",
            "score_diff": 4000,
            "probability": 0.91,
            "admission_safety_score": 86,
            "overall_score": 76.0,
            "tuition_per_year": 5200,
            "subject_requirements": ["物理"],
            "rank_reference": {"year": 2025, "min_rank": 48500},
            "recommendation_reasons": ["位次安全边际充足", "理工类院校软工专业稳定"],
            "risk_items": [],
            "evidence_ids": ["src_002"],
        },
        {
            "id": "cand_006",
            "university_name": "中原工学院",
            "university_city": "郑州",
            "province": "河南",
            "major_group": "080001",
            "major_name": "计算机科学与技术",
            "tier": "safe",
            "score_diff": 6500,
            "probability": 0.96,
            "admission_safety_score": 93,
            "overall_score": 71.0,
            "tuition_per_year": 5000,
            "subject_requirements": ["物理"],
            "rank_reference": {"year": 2025, "min_rank": 58000},
            "recommendation_reasons": ["保底院校，安全边际非常充足", "郑州市内，地理位置便利"],
            "risk_items": [],
            "evidence_ids": ["src_001"],
        },
        {
            "id": "cand_007",
            "university_name": "郑州轻工业大学",
            "university_city": "郑州",
            "province": "河南",
            "major_group": "090001",
            "major_name": "信息工程",
            "tier": "safe",
            "score_diff": 7200,
            "probability": 0.97,
            "admission_safety_score": 95,
            "overall_score": 68.5,
            "tuition_per_year": 4800,
            "subject_requirements": ["物理"],
            "rank_reference": {"year": 2025, "min_rank": 63000},
            "recommendation_reasons": ["保底充足，历年录取稳定"],
            "risk_items": [],
            "evidence_ids": ["src_001"],
        },
        {
            "id": "cand_008",
            "university_name": "河南城建学院",
            "university_city": "平顶山",
            "province": "河南",
            "major_group": "100001",
            "major_name": "计算机应用技术",
            "tier": "safe",
            "score_diff": 9000,
            "probability": 0.99,
            "admission_safety_score": 98,
            "overall_score": 60.0,
            "tuition_per_year": 4500,
            "subject_requirements": [],
            "rank_reference": {"year": 2025, "min_rank": 72000},
            "recommendation_reasons": ["最终保底，录取概率极高"],
            "risk_items": [],
            "evidence_ids": [],
        },
    ]

    tier_summary = {
        "rush": 2,
        "target": 3,
        "safe": 3,
        "high_rush": 0,
    }

    await _push_sse_event(
        run_id,
        "candidates_ready",
        {
            "total": len(scored_candidates),
            "rush": tier_summary["rush"],
            "target": tier_summary["target"],
            "safe": tier_summary["safe"],
        },
    )

    return {
        "candidates": scored_candidates,
        "scored_candidates": scored_candidates,
        "tier_summary": tier_summary,
    }


async def mock_risk(state: VolunteerPlanState) -> dict:
    """
    Mock Risk Agent node.
    Checks volunteer plan for risks: insufficient safety schools, gradient, crowding, etc.
    Real impl: calls Risk Engine with actual candidate list analysis.
    """
    run_id = state["run_id"]

    await _push_sse_event(
        run_id,
        "node_started",
        {"node": "risk", "message": "正在进行风险体检"},
    )

    await asyncio.sleep(1.5)

    risk_items = [
        {
            "risk_type": "gradient_too_dense",
            "severity": "medium",
            "message": "候选志愿中部分冲击志愿梯度过密，建议适当拉开位次差距",
            "targets": ["cand_001", "cand_002"],
        },
    ]

    overall_risk_level = "medium"

    await _push_sse_event(
        run_id,
        "risk_found",
        {
            "risk_type": "gradient_too_dense",
            "severity": "medium",
            "message": "候选志愿梯度过密",
        },
    )

    return {
        "risk_items": risk_items,
        "overall_risk_level": overall_risk_level,
        "needs_human_review": False,
        "review_reasons": [],
    }


async def mock_report(state: VolunteerPlanState) -> dict:
    """
    Mock Report Agent node.
    Assembles the final report with three plan tiers and saves to DB.
    Real impl: calls Report Agent (LLM) with template + evidence context.
    """
    from sqlalchemy import select

    from app.database import async_session_maker
    from app.models.report import Report

    run_id = state["run_id"]

    await _push_sse_event(
        run_id,
        "node_started",
        {"node": "report", "message": "正在生成三套方案报告"},
    )

    await asyncio.sleep(1.5)

    scored = state.get("scored_candidates", [])

    # Build three plan tiers from scored_candidates
    rush_candidates = [c for c in scored if c["tier"] in ("rush", "high_rush")]
    target_candidates = [c for c in scored if c["tier"] == "target"]
    safe_candidates = [c for c in scored if c["tier"] == "safe"]

    plan_json = {
        "plans": [
            {
                "type": "conservative",
                "label": "保守型",
                "description": "以稳妥为主，保底充足，风险最低",
                "candidates": target_candidates + safe_candidates,
            },
            {
                "type": "balanced",
                "label": "均衡型",
                "description": "冲稳保比例合理，综合评分最优",
                "candidates": rush_candidates[:1] + target_candidates + safe_candidates[:2],
            },
            {
                "type": "aggressive",
                "label": "进取型",
                "description": "优先冲击更高目标，保底数量满足最低要求",
                "candidates": rush_candidates + target_candidates + safe_candidates[:1],
            },
        ]
    }

    report_id = str(uuid4())

    # Persist to DB using a fresh session (worker runs outside request context)
    async with async_session_maker() as db:
        report = Report(
            id=report_id,
            profile_id=state.get("profile_id") or None,
            run_id=run_id,
            status="completed",
            risk_level=state.get("overall_risk_level", "medium"),
            risk_score=55.0,
            plan_json=plan_json,
            evidence_json=state.get("evidence_list", []),
            dataset_version=state.get("dataset_version"),
        )
        db.add(report)
        await db.commit()

    await _push_sse_event(
        run_id,
        "completed",
        {
            "report_id": report_id,
            "risk_level": state.get("overall_risk_level", "medium"),
            "needs_review": state.get("needs_human_review", False),
        },
    )

    return {
        "report_id": report_id,
        "report_draft": plan_json,
        "compliance_passed": True,
        "compliance_issues": [],
        "completed_at": datetime.now(UTC).isoformat(),
    }
