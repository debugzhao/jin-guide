"""
三套志愿方案生成器 (PRD §8.2)
conservative / balanced / aggressive — 冲稳保比例 + safe 硬底 ≥10
"""
from __future__ import annotations

from typing import Literal

PlanType = Literal["conservative", "balanced", "aggressive"]

# 冲(high_rush) / 冲(rush) / 稳(target) / 保(safe)
_PLAN_RATIOS: dict[str, dict[str, float]] = {
    "conservative": {"high_rush": 0.00, "rush": 0.20, "target": 0.40, "safe": 0.40},
    "balanced":     {"high_rush": 0.05, "rush": 0.30, "target": 0.40, "safe": 0.25},
    "aggressive":   {"high_rush": 0.15, "rush": 0.35, "target": 0.35, "safe": 0.15},
}

_SAFE_HARD_FLOOR = 10
_TIER_ORDER = {"high_rush": 0, "rush": 1, "target": 2, "safe": 3}


def _pick_top(candidates: list[dict], tier: str, n: int) -> list[dict]:
    pool = [c for c in candidates if c.get("tier") == tier]
    pool.sort(key=lambda c: c.get("overall_score", 0), reverse=True)
    return pool[:n]


def _enforce_safe_floor(counts: dict[str, int]) -> dict[str, int]:
    deficit = max(0, _SAFE_HARD_FLOOR - counts["safe"])
    if deficit == 0:
        return counts
    result = dict(counts)
    for donor in ("rush", "target", "high_rush"):
        reducible = min(result[donor], deficit)
        result[donor] -= reducible
        result["safe"] += reducible
        deficit -= reducible
        if deficit == 0:
            break
    return result


def generate_plans(
    scored_candidates: list[dict],
    max_volunteers: int = 96,
) -> dict[str, dict]:
    """
    Generate conservative / balanced / aggressive plans.

    Each candidate must have: tier, overall_score, university_id, university_name,
    major_name, rank_gap.

    Returns:
        {
          "conservative": {
              "volunteers": [...sorted by tier→score],
              "tier_distribution": {"high_rush":N, "rush":N, "target":N, "safe":N},
              "total": N,
          },
          ...
        }
    """
    plans: dict[str, dict] = {}

    for plan_type, ratios in _PLAN_RATIOS.items():
        counts: dict[str, int] = {}
        remaining = max_volunteers
        for tier in ("high_rush", "rush", "target"):
            n = round(ratios[tier] * max_volunteers)
            counts[tier] = n
            remaining -= n
        counts["safe"] = max(0, remaining)
        counts = _enforce_safe_floor(counts)

        volunteers: list[dict] = []
        for tier, n in counts.items():
            volunteers.extend(_pick_top(scored_candidates, tier, n))

        volunteers.sort(key=lambda c: (
            _TIER_ORDER.get(c.get("tier", "target"), 2),
            -c.get("overall_score", 0),
        ))

        plans[plan_type] = {
            "volunteers": volunteers,
            "tier_distribution": counts,
            "total": len(volunteers),
        }

    return plans
