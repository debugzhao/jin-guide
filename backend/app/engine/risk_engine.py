"""
志愿表风险引擎 (PRD §8.3)
四项检查：保底充足性 / 梯度压缩 / 专业扎堆 / 不服从调剂专业
"""
from __future__ import annotations

from collections import Counter
from typing import Literal

RiskSeverity = Literal["high", "medium", "low"]

_SAFETY_FLOOR = 10
_GRADIENT_MIN_GAP = 2000      # 同档相邻院校最小位次差
_CROWDING_THRESHOLD = 0.35    # 同类专业占总志愿比例阈值
_CROWDING_WARN_THRESHOLD = 0.25


def _item(
    risk_type: str,
    severity: RiskSeverity,
    message: str,
    targets: list[str] | None = None,
) -> dict:
    return {
        "risk_type": risk_type,
        "severity": severity,
        "message": message,
        "targets": targets or [],
    }


def check_safety_adequacy(candidates: list[dict]) -> list[dict]:
    """保底充足性：safe 档绝对数量 ≥ 10"""
    safe_count = sum(1 for c in candidates if c.get("tier") == "safe")
    if safe_count == 0:
        return [_item(
            "safety_adequacy", "high",
            f"志愿表中无保底院校（safe=0），录取风险极高，请至少填入 {_SAFETY_FLOOR} 所保底院校",
        )]
    if safe_count < _SAFETY_FLOOR:
        return [_item(
            "safety_adequacy", "high",
            f"保底院校数量不足（当前 {safe_count} 所，建议 ≥{_SAFETY_FLOOR} 所），"
            "一旦冲刺全部落榜将面临无学可上风险",
        )]
    return []


def check_gradient(candidates: list[dict]) -> list[dict]:
    """梯度压缩检查：同档相邻院校位次差过小"""
    items: list[dict] = []
    tier_groups: dict[str, list[dict]] = {}
    for c in candidates:
        tier = c.get("tier", "target")
        tier_groups.setdefault(tier, []).append(c)

    for tier, group in tier_groups.items():
        if len(group) < 2:
            continue
        group_sorted = sorted(group, key=lambda c: c.get("rank_gap", 0))
        compressed: list[str] = []
        for i in range(1, len(group_sorted)):
            gap = abs(
                group_sorted[i].get("rank_gap", 0)
                - group_sorted[i - 1].get("rank_gap", 0)
            )
            if gap < _GRADIENT_MIN_GAP:
                name_a = group_sorted[i - 1].get("university_name", "?")
                name_b = group_sorted[i].get("university_name", "?")
                compressed.append(f"{name_a}↔{name_b}(位次差{int(gap)})")

        if not compressed:
            continue
        severity: RiskSeverity = "medium" if len(compressed) >= 3 else "low"
        items.append(_item(
            "gradient_compressed", severity,
            f"【{tier}】档 {len(compressed)} 处院校位次梯度偏小"
            f"（相邻位次差<{_GRADIENT_MIN_GAP}），建议适当拉开梯度",
            targets=compressed[:5],
        ))

    return items


def check_crowding(candidates: list[dict]) -> list[dict]:
    """专业扎堆检查：同类专业占比过高"""
    items: list[dict] = []
    total = len(candidates)
    if total == 0:
        return items

    cats = [
        c.get("major_category") or c.get("major_name", "")[:3]
        for c in candidates
    ]
    counter = Counter(cats)

    for cat, count in counter.most_common(3):
        ratio = count / total
        if ratio >= _CROWDING_THRESHOLD:
            items.append(_item(
                "major_crowding", "medium",
                f"专业集中度过高：【{cat}】类占 {count}/{total}（{ratio:.0%}），"
                "建议分散到 2-3 个专业方向以降低整体风险",
            ))
        elif ratio >= _CROWDING_WARN_THRESHOLD:
            items.append(_item(
                "major_crowding", "low",
                f"专业略有集中：【{cat}】类占 {count}/{total}（{ratio:.0%}），可适当分散",
            ))

    return items


def check_rejected_major(
    candidates: list[dict],
    rejected_majors: list[str],
) -> list[dict]:
    """不服从调剂专业检查：志愿表中包含考生明确拒绝的专业"""
    if not rejected_majors:
        return []

    violations: list[str] = []
    for c in candidates:
        major = c.get("major_name", "")
        for r in rejected_majors:
            if r in major or major in r:
                violations.append(
                    f'{c.get("university_name","?")} - {major}'
                    f'（含不服从专业【{r}】）'
                )
                break

    if not violations:
        return []

    return [_item(
        "rejected_major", "high",
        f"志愿表中包含 {len(violations)} 个不服从调剂专业，"
        "若未能录取首选专业将直接被退档，请及时移除或标注",
        targets=violations,
    )]


def run_all_checks(
    candidates: list[dict],
    rejected_majors: list[str] | None = None,
) -> tuple[list[dict], Literal["low", "medium", "high"]]:
    """
    运行全部四项检查，返回 (risk_items, overall_level)。
    """
    all_items: list[dict] = []
    all_items.extend(check_safety_adequacy(candidates))
    all_items.extend(check_gradient(candidates))
    all_items.extend(check_crowding(candidates))
    all_items.extend(check_rejected_major(candidates, rejected_majors or []))

    has_high = any(i["severity"] == "high" for i in all_items)
    has_medium = any(i["severity"] == "medium" for i in all_items)
    overall: Literal["low", "medium", "high"] = (
        "high" if has_high else ("medium" if has_medium else "low")
    )
    return all_items, overall
