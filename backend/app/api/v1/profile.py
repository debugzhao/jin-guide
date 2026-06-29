from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.profile import Preference, StudentProfile

router = APIRouter()


class PreferenceIn(BaseModel):
    major_prefs: Optional[list] = None
    city_prefs: Optional[list] = None
    rejected_majors: Optional[list] = None
    career_priority: Optional[str] = None


class ProfileIn(BaseModel):
    user_id: Optional[str] = None
    province: str
    score: Optional[int] = None
    rank: Optional[int] = None
    subjects: Optional[list] = None
    batch: str = "本科批"
    family_budget: Optional[int] = None
    risk_style: Optional[str] = None
    preference: Optional[PreferenceIn] = None


class ProfileOut(BaseModel):
    id: str
    user_id: Optional[str]
    province: str
    score: Optional[int]
    rank: Optional[int]
    subjects: Optional[list]
    batch: str
    family_budget: Optional[int]
    risk_style: Optional[str]
    completeness_score: float
    created_at: str
    updated_at: str
    preference: Optional[dict] = None


def _compute_completeness(profile: StudentProfile) -> float:
    """
    Compute profile completeness score (0.0 – 1.0) based on non-null field ratio.
    Weighted: province+score/rank are required (higher weight); others are optional.
    """
    fields = {
        "province": profile.province,
        "score": profile.score,
        "rank": profile.rank,
        "subjects": profile.subjects,
        "batch": profile.batch,
        "family_budget": profile.family_budget,
        "risk_style": profile.risk_style,
    }
    weights = {
        "province": 3,
        "score": 2,
        "rank": 2,
        "subjects": 2,
        "batch": 1,
        "family_budget": 1,
        "risk_style": 1,
    }
    total_weight = sum(weights.values())
    earned = sum(
        weights[k] for k, v in fields.items() if v is not None
    )
    return round(earned / total_weight, 4)


@router.post("", response_model=ProfileOut, status_code=201)
async def create_profile(
    body: ProfileIn,
    db: AsyncSession = Depends(get_db),
):
    """Create a new StudentProfile and optionally its Preference."""
    profile = StudentProfile(
        id=str(uuid4()),
        user_id=body.user_id,
        province=body.province,
        score=body.score,
        rank=body.rank,
        subjects=body.subjects,
        batch=body.batch,
        family_budget=body.family_budget,
        risk_style=body.risk_style,
    )
    profile.completeness_score = _compute_completeness(profile)

    db.add(profile)

    pref_out = None
    if body.preference:
        pref = Preference(
            id=str(uuid4()),
            profile_id=profile.id,
            major_prefs=body.preference.major_prefs,
            city_prefs=body.preference.city_prefs,
            rejected_majors=body.preference.rejected_majors,
            career_priority=body.preference.career_priority,
        )
        db.add(pref)
        pref_out = {
            "major_prefs": pref.major_prefs,
            "city_prefs": pref.city_prefs,
            "rejected_majors": pref.rejected_majors,
            "career_priority": pref.career_priority,
        }

    await db.commit()
    await db.refresh(profile)

    return ProfileOut(
        id=profile.id,
        user_id=profile.user_id,
        province=profile.province,
        score=profile.score,
        rank=profile.rank,
        subjects=profile.subjects,
        batch=profile.batch,
        family_budget=profile.family_budget,
        risk_style=profile.risk_style,
        completeness_score=profile.completeness_score,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
        preference=pref_out,
    )


@router.get("/{profile_id}", response_model=ProfileOut)
async def get_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch a StudentProfile with its Preference."""
    result = await db.execute(
        select(StudentProfile).where(StudentProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="profile not found")

    pref_result = await db.execute(
        select(Preference).where(Preference.profile_id == profile_id)
    )
    pref = pref_result.scalar_one_or_none()
    pref_out = None
    if pref:
        pref_out = {
            "major_prefs": pref.major_prefs,
            "city_prefs": pref.city_prefs,
            "rejected_majors": pref.rejected_majors,
            "career_priority": pref.career_priority,
        }

    return ProfileOut(
        id=profile.id,
        user_id=profile.user_id,
        province=profile.province,
        score=profile.score,
        rank=profile.rank,
        subjects=profile.subjects,
        batch=profile.batch,
        family_budget=profile.family_budget,
        risk_style=profile.risk_style,
        completeness_score=profile.completeness_score,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
        preference=pref_out,
    )
