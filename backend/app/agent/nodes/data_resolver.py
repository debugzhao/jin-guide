"""
Data Resolver node (M2): loads student profile from DB, checks data
availability for the province/batch, locks dataset_version.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
        await redis_client.expire(f"sse:{run_id}", 604800)
    finally:
        await redis_client.aclose()


def _load_profile_sync(profile_id: str) -> tuple[dict, list[str], str]:
    """Run in thread pool — uses sync SQLAlchemy Session."""
    from app.database import SyncSessionLocal
    from app.models.admission import AdmissionScore
    from app.models.profile import Preference, StudentProfile

    with SyncSessionLocal() as db:
        profile: StudentProfile | None = db.get(StudentProfile, profile_id)
        if not profile:
            return {}, [f"档案 {profile_id} 不存在"], "unknown"

        pref_row = db.execute(
            select(Preference).where(Preference.profile_id == profile_id)
        ).scalar_one_or_none()

        subjects: list[str] = profile.subjects or []
        subject_type = "physics" if "物理" in subjects else "history"
        batch = profile.batch or "本科批"

        profile_dict: dict = {
            "id": profile.id,
            "province": profile.province,
            "score": profile.score or 0,
            "rank": profile.rank or 0,
            "subjects": subjects,
            "subject_type": subject_type,
            "batch": batch,
            "family_budget": profile.family_budget,
            "risk_style": profile.risk_style or "balanced",
            "major_prefs": (pref_row.major_prefs or []) if pref_row else [],
            "city_prefs": (pref_row.city_prefs or []) if pref_row else [],
            "rejected_majors": (pref_row.rejected_majors or []) if pref_row else [],
        }

        count: int = db.execute(
            select(func.count(AdmissionScore.id)).where(
                AdmissionScore.province == profile.province,
                AdmissionScore.batch == batch,
                AdmissionScore.subject_type == subject_type,
            )
        ).scalar_one_or_none() or 0

        warnings: list[str] = []
        if count < 10:
            warnings.append(
                f"{profile.province}{batch}历史数据不足（{count}条），推荐质量可能下降"
            )

        year = datetime.now().year
        dataset_version = f"{profile.province}_{year}_v1"
        return profile_dict, warnings, dataset_version


async def data_resolver(state: VolunteerPlanState) -> dict:
    run_id = state["run_id"]
    profile_id = state["profile_id"]

    await _push_sse(run_id, "node_started", {"node": "data_resolver", "message": "正在确认数据版本"})

    try:
        profile_dict, data_warnings, dataset_version = await asyncio.to_thread(
            _load_profile_sync, profile_id
        )
    except Exception as exc:
        logger.exception("data_resolver failed to load profile")
        profile_dict = {}
        data_warnings = [f"档案加载失败：{exc!s}"]
        dataset_version = "unknown"

    await _push_sse(
        run_id,
        "node_completed",
        {
            "node": "data_resolver",
            "dataset_version": dataset_version,
            "message": f"数据版本已锁定：{dataset_version}",
        },
    )

    return {
        "profile": profile_dict,
        "profile_complete": bool(profile_dict.get("rank") and profile_dict.get("score")),
        "profile_pending_questions": [],
        "dataset_version": dataset_version,
        "data_warnings": data_warnings,
    }
