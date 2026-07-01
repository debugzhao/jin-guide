"""
POST /api/v1/volunteer/check — 志愿表体检同步接口 (PRD §8.3)
< 5s 同步响应；不调用 LLM
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_sync_db
from app.engine.risk_engine import run_all_checks

router = APIRouter()


class VolunteerItem(BaseModel):
    university_id: str = ""
    university_name: str
    major_name: str
    major_category: str = ""
    tier: Literal["high_rush", "rush", "target", "safe"] = "target"
    rank_gap: float = 0.0
    overall_score: float = 0.0


class VolunteerCheckIn(BaseModel):
    volunteers: list[VolunteerItem] = Field(..., min_length=1)
    rejected_majors: list[str] = []


class RiskItemOut(BaseModel):
    risk_type: str
    severity: Literal["high", "medium", "low"]
    message: str
    targets: list[str] = []


class VolunteerCheckOut(BaseModel):
    overall_risk: Literal["low", "medium", "high"]
    risk_score: int
    risk_items: list[RiskItemOut]
    tier_distribution: dict[str, int]
    safe_count: int
    total: int


def _risk_score(items: list[dict]) -> int:
    penalty = sum(
        20 if i["severity"] == "high" else (10 if i["severity"] == "medium" else 5)
        for i in items
    )
    return max(0, 100 - penalty)


@router.post("/check", response_model=VolunteerCheckOut)
def check_volunteer(
    body: VolunteerCheckIn,
    db: Session = Depends(get_sync_db),
) -> VolunteerCheckOut:
    candidates = [v.model_dump() for v in body.volunteers]
    risk_items, overall = run_all_checks(candidates, body.rejected_majors)

    tier_dist: dict[str, int] = {"high_rush": 0, "rush": 0, "target": 0, "safe": 0}
    for c in candidates:
        t = c.get("tier", "target")
        tier_dist[t] = tier_dist.get(t, 0) + 1

    return VolunteerCheckOut(
        overall_risk=overall,
        risk_score=_risk_score(risk_items),
        risk_items=[RiskItemOut(**item) for item in risk_items],
        tier_distribution=tier_dist,
        safe_count=tier_dist.get("safe", 0),
        total=len(candidates),
    )
