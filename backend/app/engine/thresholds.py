"""
省份冲稳保位次阈值 + 志愿数上限的统一读取入口 (docs/03_data_model.md §2.5, CLAUDE.md「志愿数上限」约束)。

替代 scoring.py / risk.py / planner.py 调用方里原有的硬编码阈值，
让数据运营可以直接改 province_thresholds 表，不需要改代码。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admission import ProvinceThreshold

DEFAULT_MAX_VOLUNTEERS = 96


@dataclass(frozen=True)
class ThresholdValues:
    """与 province_thresholds 表列一一对应；无匹配记录时使用这里的默认值兜底。"""

    high_rush_rank_gap: int = 5000
    rush_rank_gap_min: int = 1000
    rush_rank_gap_max: int = 5000
    target_rank_gap: int = 1000
    safe_rank_gap: int = 2000
    max_volunteers: int = DEFAULT_MAX_VOLUNTEERS


_FALLBACK = ThresholdValues()


def get_province_threshold(db: Session, province: str) -> ThresholdValues:
    """
    读取指定省份最新一年的 province_thresholds 配置。
    表内没有该省份记录时（尚未运营配置的省份）回退到全国默认阈值，
    保证数据覆盖不到的省份依然能正常生成报告，而不是抛错。
    """
    row = (
        db.execute(
            select(ProvinceThreshold)
            .where(ProvinceThreshold.province == province)
            .order_by(ProvinceThreshold.year.desc())
        )
        .scalars()
        .first()
    )

    if row is None:
        return _FALLBACK

    return ThresholdValues(
        high_rush_rank_gap=row.high_rush_rank_gap,
        rush_rank_gap_min=row.rush_rank_gap_min,
        rush_rank_gap_max=row.rush_rank_gap_max,
        target_rank_gap=row.target_rank_gap,
        safe_rank_gap=row.safe_rank_gap,
        max_volunteers=row.max_volunteers,
    )
