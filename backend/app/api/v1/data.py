from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_sync_db
from app.models.admission import AdmissionScore, University

router = APIRouter()


class DataAvailabilityOut(BaseModel):
    province: str
    year: int
    batch: str
    status: str
    dataset_version: str
    available: bool
    warnings: list
    # max_volunteers: used by frontend to cap volunteer table size (see PRD 8.3)
    max_volunteers: int


@router.get("/availability", response_model=DataAvailabilityOut)
def check_data_availability(
    province: str = "河南",
    year: int = 2025,
    batch: str = "本科批",
    db: Session = Depends(get_sync_db),
) -> DataAvailabilityOut:
    """
    Query real data availability: count admission score records for province/year/batch.
    Falls back gracefully if no data exists.
    """
    count = db.execute(
        select(func.count()).where(
            AdmissionScore.province == province,
            AdmissionScore.year == year,
            AdmissionScore.batch == batch,
        )
    ).scalar_one_or_none() or 0

    available = count > 0
    warnings: list[str] = []

    if not available:
        warnings.append(
            f"暂无 {province} {year} 年 {batch} 录取数据，建议使用相邻年份参考"
        )
        # Try adjacent year
        nearest_year = db.execute(
            select(func.max(AdmissionScore.year)).where(
                AdmissionScore.province == province,
                AdmissionScore.batch == batch,
            )
        ).scalar_one_or_none()
        if nearest_year:
            warnings.append(f"可用最近数据年份：{nearest_year}")

    dataset_version = f"{province.replace('省', '')}_{year}_v1"

    return DataAvailabilityOut(
        province=province,
        year=year,
        batch=batch,
        status="published" if available else "unavailable",
        dataset_version=dataset_version,
        available=available,
        warnings=warnings,
        max_volunteers=96,  # Province-specific cap; 河南/山东 default 96
    )
