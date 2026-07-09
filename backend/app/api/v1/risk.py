"""
POST /api/v1/risk/preview — 快速风险画像（< 2s）

输入：省份、分数/位次、批次、选科、是否有体检限制
输出：整体风险等级、分档位次、可报批次列表、风险项列表
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_sync_db
from app.engine.thresholds import get_province_threshold
from app.models.admission import AdmissionScore, RankSegment, University

router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class RiskPreviewIn(BaseModel):
    province: str = "河南"
    score: int
    rank: int
    batch: str = "本科批"
    subject_type: Literal["physics", "history"] = "physics"
    has_physical_limits: bool = False
    family_budget_per_year: int | None = None  # 元/年，None=不限


class RiskItem(BaseModel):
    type: str          # subject / medical / budget / data
    level: Literal["error", "warning", "info"]
    message: str


class RiskPreviewOut(BaseModel):
    overall_risk: Literal["low", "medium", "high", "unknown"]
    risk_score: float                    # 0-100，越高风险越大
    score_band: str                      # 距批次线描述，例如 "高于批次线 93 分"
    rank_band: str                       # 距一本线描述
    eligible_batches: list[str]          # 可报批次列表
    tier_counts: dict[str, int]          # {"冲": N, "稳": N, "保": N} 可选院校数估算
    risk_items: list[RiskItem]
    data_available: bool                 # 是否有充足历史数据


# 河南省 物理类 批次线（近三年参考，用于 score_band 计算）
_HENAN_BATCH_LINE: dict[str, dict[str, int]] = {
    "本科批": {"physics": 499, "history": 439},
    "专科批": {"physics": 200, "history": 200},
}



@router.post("/preview", response_model=RiskPreviewOut)
def risk_preview(
    body: RiskPreviewIn,
    db: Session = Depends(get_sync_db),
) -> RiskPreviewOut:
    """
    快速风险画像。
    - 不经过 LLM，全部 SQL + 规则计算
    - 目标响应 < 2s
    """
    risk_items: list[RiskItem] = []

    # ── 1. 批次线距离 ─────────────────────────────────────────────────────────
    batch_line = _HENAN_BATCH_LINE.get(body.batch, {}).get(body.subject_type, 0)
    score_gap = body.score - batch_line
    if score_gap >= 0:
        score_band = f"高于{body.batch}线 {score_gap} 分"
    else:
        score_band = f"低于{body.batch}线 {abs(score_gap)} 分"
        risk_items.append(RiskItem(
            type="batch",
            level="error",
            message=f"分数低于 {body.province} {body.batch} 参考线 {abs(score_gap)} 分，可能无法参与该批次录取",
        ))

    # ── 2. 位次带描述 ─────────────────────────────────────────────────────────
    rank = body.rank
    if rank <= 1000:
        rank_band = "全省前 1000 名"
    elif rank <= 5000:
        rank_band = f"全省约前 {rank // 1000}k 名"
    elif rank <= 50000:
        rank_band = f"全省约 {rank // 10000}w{(rank % 10000) // 1000}k 名"
    else:
        rank_band = f"全省第 {rank:,} 名"

    # ── 3. 可报批次列表 ───────────────────────────────────────────────────────
    eligible_batches: list[str] = []
    for batch_name, lines in _HENAN_BATCH_LINE.items():
        line = lines.get(body.subject_type, 0)
        if body.score >= line:
            eligible_batches.append(batch_name)

    # ── 4. 院校分档估算（冲稳保） ─────────────────────────────────────────────
    # 以 2025 年数据为基准（无则回退到最近年份）
    tier_counts = _calc_tier_counts(
        rank=body.rank,
        province=body.province,
        batch=body.batch,
        subject_type=body.subject_type,
        db=db,
    )
    data_available = sum(tier_counts.values()) > 0

    if not data_available:
        risk_items.append(RiskItem(
            type="data",
            level="warning",
            message=f"暂无 {body.province} {body.batch} {body.subject_type} 类历史录取数据，风险评估结果仅供参考",
        ))

    # ── 5. 体检风险提示 ───────────────────────────────────────────────────────
    if body.has_physical_limits:
        risk_items.append(RiskItem(
            type="medical",
            level="warning",
            message="考生标注有身体限制，建议在报考前逐一核查目标专业的体检要求",
        ))

    # ── 6. 预算提示 ───────────────────────────────────────────────────────────
    if body.family_budget_per_year is not None and body.family_budget_per_year < 6000:
        high_tuition_count = _count_high_tuition_schools(
            budget=body.family_budget_per_year, db=db
        )
        if high_tuition_count > 0:
            risk_items.append(RiskItem(
                type="budget",
                level="info",
                message=(
                    f"位次段内约有 {high_tuition_count} 所院校学费可能超出家庭年预算 "
                    f"{body.family_budget_per_year:,} 元，建议填报时核查学费"
                ),
            ))

    # ── 7. 综合风险评分 ───────────────────────────────────────────────────────
    overall_risk, risk_score = _calc_overall_risk(
        score_gap=score_gap,
        risk_items=risk_items,
        tier_counts=tier_counts,
    )

    return RiskPreviewOut(
        overall_risk=overall_risk,
        risk_score=risk_score,
        score_band=score_band,
        rank_band=rank_band,
        eligible_batches=eligible_batches,
        tier_counts=tier_counts,
        risk_items=risk_items,
        data_available=data_available,
    )


# ── 内部辅助函数 ──────────────────────────────────────────────────────────────

def _calc_tier_counts(
    rank: int, province: str, batch: str, subject_type: str, db: Session
) -> dict[str, int]:
    """统计考生位次下各分档可选院校数（冲/稳/保）。"""
    # 使用最近可用年份
    year_row = db.execute(
        select(func.max(AdmissionScore.year)).where(
            AdmissionScore.province == province,
            AdmissionScore.batch == batch,
            AdmissionScore.subject_type == subject_type,
        )
    ).scalar_one_or_none()

    if year_row is None:
        return {"冲": 0, "稳": 0, "保": 0}

    year: int = year_row
    rows = db.execute(
        select(AdmissionScore.avg_rank).where(
            AdmissionScore.province == province,
            AdmissionScore.year == year,
            AdmissionScore.batch == batch,
            AdmissionScore.subject_type == subject_type,
            AdmissionScore.avg_rank.is_not(None),
        )
    ).scalars().all()

    thresholds = get_province_threshold(db, province)

    rush = target = safe = 0
    for avg_rank in rows:
        rank_gap = avg_rank - rank  # 正值 = 历史均值位次 > 考生位次 → 院校更难
        if rank_gap > thresholds.safe_rank_gap:
            safe += 1
        elif rank_gap > thresholds.rush_rank_gap_min:
            target += 1
        else:
            rush += 1

    return {"冲": rush, "稳": target, "保": safe}


def _count_high_tuition_schools(budget: int, db: Session) -> int:
    """统计学费超出预算的院校数。"""
    count = db.execute(
        select(func.count()).where(
            University.annual_tuition_max > budget,
        )
    ).scalar_one_or_none()
    return count or 0


def _calc_overall_risk(
    score_gap: int,
    risk_items: list[RiskItem],
    tier_counts: dict[str, int],
) -> tuple[str, float]:
    """综合风险等级和评分（0-100，越高风险越大）。"""
    error_count = sum(1 for r in risk_items if r.level == "error")
    warning_count = sum(1 for r in risk_items if r.level == "warning")

    # 基础分：距批次线每低 10 分 +10 分风险
    base_score = max(0.0, min(100.0, 50.0 - score_gap * 0.5))
    penalty = error_count * 20.0 + warning_count * 5.0
    risk_score = min(100.0, base_score + penalty)

    if error_count >= 1 or risk_score >= 80:
        overall = "high"
    elif risk_score >= 50 or warning_count >= 2:
        overall = "medium"
    elif risk_score < 30 and score_gap >= 50:
        overall = "low"
    else:
        overall = "medium"

    return overall, round(risk_score, 1)
