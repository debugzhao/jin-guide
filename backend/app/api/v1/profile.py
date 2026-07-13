import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, get_sync_db
from app.models.admission import AdmissionScore, SubjectRequirement
from app.models.profile import Preference, StudentProfile

logger = logging.getLogger(__name__)

router = APIRouter()

# 建档字段依赖顺序（纯配置驱动，不调用 LLM，见 docs/backend-prd-v2.md §5.6）
_FIELD_ORDER = [
    "province",
    "batch",
    "score",
    "rank",
    "subjects",
    "gender",
    "has_physical_limits",
    "family_budget",
    "risk_style",
    "city_prefs",
    "major_prefs",
]


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


# ── 建档单字段实时校验 (docs/backend-prd-v2.md §5.6) ─────────────────────────────

class FieldCheckIn(BaseModel):
    profile_id: Optional[str] = None
    field: str
    value: Any
    known_fields: dict[str, Any] = {}


class FieldCheckOption(BaseModel):
    action: str
    label: str


class FieldCheckIssue(BaseModel):
    rule: str
    message: str
    options: list[FieldCheckOption]


class FieldCheckOut(BaseModel):
    status: Literal["ok", "needs_clarification"]
    next_fields: list[str] = []
    issue: Optional[FieldCheckIssue] = None


def _next_fields(known: dict[str, Any], just_submitted: str) -> list[str]:
    """纯配置驱动的字段依赖图：跳过已知字段，返回接下来最多 3 个待填字段。"""
    known_now = set(known.keys()) | {just_submitted}
    return [f for f in _FIELD_ORDER if f not in known_now][:3]


def _check_rank_against_batch(
    rank: int, province: str, batch: str, subject_type: str, db: Session
) -> Optional[FieldCheckIssue]:
    """位次是否具备目标批次报考资格；无历史数据时不阻断（PARTIAL 视为通过）。"""
    from app.engine.rules import check_batch_eligibility

    year = db.execute(
        select(func.max(AdmissionScore.year)).where(
            AdmissionScore.province == province,
            AdmissionScore.batch == batch,
            AdmissionScore.subject_type == subject_type,
        )
    ).scalar_one_or_none()
    if year is None:
        return None

    result = check_batch_eligibility(
        student_rank=rank,
        province=province,
        target_batch=batch,
        year=year,
        subject_type=subject_type,
        db=db,
    )
    if not result.is_error:
        return None

    return FieldCheckIssue(
        rule="batch_ineligible",
        message=result.text,
        options=[
            FieldCheckOption(action="adjust_rank_or_batch", label="调整位次或批次"),
            FieldCheckOption(action="continue_anyway", label="仍按此继续"),
        ],
    )


def _check_subject_combo(
    subjects: list[str], province: str, batch: str, db: Session
) -> Optional[FieldCheckIssue]:
    """
    选科组合在该省份/批次是否有任意专业组能满足（required_subjects ⊆ 已选科目，
    且 optional_subjects 里满足 optional_required_count）。
    完全没有选科要求数据时不阻断（数据缺口而非矛盾）。
    """
    student_set = set(subjects or [])

    rows = db.execute(
        select(
            SubjectRequirement.required_subjects,
            SubjectRequirement.optional_subjects,
            SubjectRequirement.optional_required_count,
        )
        .join(AdmissionScore, AdmissionScore.university_id == SubjectRequirement.university_id)
        .where(
            AdmissionScore.province == province,
            AdmissionScore.batch == batch,
        )
        .limit(500)
    ).all()

    if not rows:
        return None

    for required, optional, opt_count in rows:
        required = required or []
        if any(s not in student_set for s in required):
            continue
        optional = optional or []
        opt_count = opt_count or 0
        if optional and opt_count > 0:
            matched = [s for s in optional if s in student_set]
            if len(matched) < opt_count:
                continue
        return None  # 找到至少一个能满足的专业组

    return FieldCheckIssue(
        rule="subject_combination_no_admission_plan",
        message=f"该选科组合在 {province}{batch} 暂无对应招生计划",
        options=[
            FieldCheckOption(action="adjust_subjects", label="调整选科"),
            FieldCheckOption(action="continue_anyway", label="仍按此继续"),
        ],
    )


@router.post("/field-check", response_model=FieldCheckOut)
def field_check(
    body: FieldCheckIn,
    db: Session = Depends(get_sync_db),
) -> FieldCheckOut:
    """
    对话式建档每提交一个字段做前置校验，判断是否需要 Agent 介入追问。
    字段排序/跳过逻辑是纯配置驱动的字段依赖图；矛盾检测复用 Rule Engine 的
    确定性校验函数，均不调用 LLM（转成自然语言追问是 Profile Agent 的职责）。
    """
    known = dict(body.known_fields)
    subject_type = known.get("subject_type", "physics")

    issue: Optional[FieldCheckIssue] = None

    if body.field == "rank" and known.get("province") and known.get("batch"):
        issue = _check_rank_against_batch(
            rank=int(body.value), province=known["province"], batch=known["batch"],
            subject_type=subject_type, db=db,
        )
    elif body.field == "subjects" and known.get("province") and known.get("batch"):
        issue = _check_subject_combo(
            subjects=list(body.value or []), province=known["province"], batch=known["batch"], db=db,
        )

    if issue:
        return FieldCheckOut(status="needs_clarification", issue=issue)

    return FieldCheckOut(status="ok", next_fields=_next_fields(known, body.field))


# ── 建档意图识别（Chat-first 入口，docs/frontend-prd-v2.md §Chat-first 建档入口）─────

_INTENT_AGENT_MODEL = "profile-agent"
_INTENT_LLM_TIMEOUT = 8.0

_START_PROFILE_KEYWORDS = [
    "建档", "报志愿", "填志愿", "生成报告", "测算", "冲稳保",
    "能上什么大学", "能上什么学校", "志愿表", "帮我选大学", "选专业", "分数线",
]


class IntentIn(BaseModel):
    message: str


class IntentOut(BaseModel):
    intent: Literal["start_profile", "chitchat"]


def _keyword_fallback_intent(message: str) -> Literal["start_profile", "chitchat"]:
    return "start_profile" if any(kw in message for kw in _START_PROFILE_KEYWORDS) else "chitchat"


@router.post("/intent", response_model=IntentOut)
async def classify_intent(body: IntentIn) -> IntentOut:
    """
    判断用户消息是否表达了"开始建档/生成志愿报告"的意图，用于 Chat-first 首屏
    决定是否内联渲染建档表单（generative UI）。LLM 超时/报错/输出格式不合法时
    降级到确定性关键词兜底，接口恒可用，不阻塞前端交互。
    """
    fallback = _keyword_fallback_intent(body.message)
    try:
        async with httpx.AsyncClient(timeout=_INTENT_LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.litellm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.litellm_master_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _INTENT_AGENT_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是高考志愿助手的意图分类器。判断用户消息是否表达了"
                                "\"开始填写建档信息 / 生成志愿报告 / 测算能上的大学\"的意图。"
                                '只输出 JSON，格式为 {"intent": "start_profile"} 或 '
                                '{"intent": "chitchat"}，不要输出任何其他内容。'
                            ),
                        },
                        {"role": "user", "content": body.message},
                    ],
                    "max_tokens": 20,
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        parsed = json.loads(content)
        intent = parsed.get("intent")
        if intent in ("start_profile", "chitchat"):
            return IntentOut(intent=intent)
        return IntentOut(intent=fallback)
    except Exception as exc:
        logger.warning("intent classify LLM call failed, using keyword fallback: %s", exc)
        return IntentOut(intent=fallback)
