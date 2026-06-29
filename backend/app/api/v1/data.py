from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class DataAvailabilityOut(BaseModel):
    province: str
    year: int
    batch: str
    status: str
    dataset_version: str
    available: bool
    warnings: list
    # max_volunteers: used by frontend to cap volunteer table size (see frontend PRD 8.3)
    max_volunteers: int


@router.get("/availability", response_model=DataAvailabilityOut)
async def check_data_availability(
    province: str = "河南",
    year: int = 2026,
    batch: str = "本科批",
):
    """
    Query data availability for a province/year/batch combination.
    M1: hardcoded stub. M2: query documents/dataset_version tables.
    See PRD 5.6 for full response schema.
    """
    # M1 hardcoded response
    return DataAvailabilityOut(
        province=province,
        year=year,
        batch=batch,
        status="published",
        dataset_version="henan_2026_v1",
        available=True,
        warnings=[],
        max_volunteers=96,  # Default for 河南/山东; driven by province_thresholds in M2
    )
