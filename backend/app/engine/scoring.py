"""
推荐评分引擎：四维加权评分 + 冲稳保档位划分 (PRD §8.1.1)
"""
from __future__ import annotations

import math
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admission import AdmissionScore

TierType = Literal["high_rush", "rush", "target", "safe"]

_RECENT_YEARS = 3


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def assign_tier(rank_gap: float) -> TierType:
    """
    rank_gap = historical_avg_min_rank - student_rank
    正值 = 学生位次优于历史均值（越正越保底）
    负值 = 学生位次差于历史均值（越负越冲刺）
    """
    if rank_gap < -5000:
        return "high_rush"
    if rank_gap < -1000:
        return "rush"
    if rank_gap <= 2000:
        return "target"
    return "safe"


def compute_admission_score(
    student_rank: int,
    university_id: str,
    province: str,
    batch: str,
    subject_type: str,
    db: Session,
) -> tuple[float, float, TierType]:
    """
    Returns (admission_score 0-100, rank_gap, tier).
    Falls back to (50.0, 0.0, 'target') when no historical data.
    """
    rows = db.execute(
        select(AdmissionScore.year, AdmissionScore.min_rank)
        .where(
            AdmissionScore.university_id == university_id,
            AdmissionScore.province == province,
            AdmissionScore.batch == batch,
            AdmissionScore.subject_type == subject_type,
        )
        .order_by(AdmissionScore.year.desc())
        .limit(_RECENT_YEARS)
    ).all()

    if not rows:
        return 50.0, 0.0, "target"

    ranks = [r.min_rank for r in rows if r.min_rank is not None]
    if not ranks:
        return 50.0, 0.0, "target"

    mean = sum(ranks) / len(ranks)
    rank_gap = mean - student_rank

    if len(ranks) >= 2:
        variance = sum((r - mean) ** 2 for r in ranks) / len(ranks)
        std = math.sqrt(variance)
        stability = _clip(1.0 - std / mean, 0.0, 1.0)
    else:
        stability = 0.8  # single-year fallback

    raw = _clip(50.0 + rank_gap / 500.0 * 30.0, 0.0, 100.0)
    score = raw * 0.7 + stability * 100.0 * 0.3
    tier = assign_tier(rank_gap)
    return round(score, 2), round(rank_gap, 1), tier


def compute_major_fit_score(
    preference_majors: list[str],
    rejected_majors: list[str],
    major_name: str,
    student_subjects: list[str],
    required_subjects: list[str] | None = None,
) -> float:
    """
    preference_match*0.5 + subject_match*0.3 + rejection_penalty*0.2
    """
    if any(p in major_name or major_name in p for p in preference_majors):
        preference_match = 100.0
    elif preference_majors:
        preference_match = 20.0
    else:
        preference_match = 60.0

    if required_subjects:
        student_set = set(student_subjects)
        matched = sum(1 for s in required_subjects if s in student_set)
        if matched == len(required_subjects):
            subject_match = 100.0
        elif matched > 0:
            subject_match = 60.0
        else:
            subject_match = 30.0
    else:
        subject_match = 80.0

    if any(r in major_name or major_name in r for r in rejected_majors):
        rejection_penalty = 0.0
    else:
        rejection_penalty = 100.0

    return round(preference_match * 0.5 + subject_match * 0.3 + rejection_penalty * 0.2, 2)


def compute_city_family_score(
    university_city: str,
    university_province: str,
    preference_cities: list[str],
    home_province: str,
    family_budget_per_year: int | None,
    annual_tuition: int | None,
) -> float:
    """
    city_preference_match*0.6 + budget_fit*0.4
    """
    if preference_cities:
        if university_city in preference_cities or university_province in preference_cities:
            city_match = 100.0
        elif "不限" in preference_cities:
            city_match = 80.0
        else:
            city_match = 20.0
    else:
        city_match = 70.0 if university_province == home_province else 60.0

    if family_budget_per_year and annual_tuition:
        if annual_tuition <= family_budget_per_year:
            budget_fit = 100.0
        elif annual_tuition <= family_budget_per_year * 1.3:
            budget_fit = 50.0
        else:
            budget_fit = 0.0
    else:
        budget_fit = 70.0

    return round(city_match * 0.6 + budget_fit * 0.4, 2)


def compute_cost_risk_score(risk_items: list[dict]) -> float:
    """
    cost_risk_score = 100 - sum(penalties)
    high=-20, medium=-10, low=-5
    """
    penalty = 0.0
    for item in risk_items:
        sev = item.get("severity", "low")
        if sev == "high":
            penalty += 20.0
        elif sev == "medium":
            penalty += 10.0
        else:
            penalty += 5.0
    return round(_clip(100.0 - penalty, 0.0, 100.0), 2)


def compute_overall_score(
    admission_score: float,
    major_fit_score: float,
    city_family_score: float,
    cost_risk_score: float,
) -> float:
    """PRD §8.1.1: 0.40/0.25/0.20/0.15 加权"""
    return round(
        admission_score * 0.40
        + major_fit_score * 0.25
        + city_family_score * 0.20
        + cost_risk_score * 0.15,
        2,
    )
