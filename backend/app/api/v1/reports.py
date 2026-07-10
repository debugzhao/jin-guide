from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cursor import decode_cursor, encode_cursor
from app.api.dependencies import Identity, get_identity
from app.api.v1.mock_data import MOCK_REPORT_EVIDENCE, MOCK_REPORT_PLAN
from app.database import get_db
from app.models.agent_run import AgentRun
from app.models.profile import Preference, StudentProfile
from app.models.report import Report

router = APIRouter()

# /refine 只接受这些"轻量约束"字段（白名单）；命中之外的任何 key 都要求走完整重新生成
# (docs/backend-prd-v2.md §5.9)
_LIGHT_PATCH_KEYS = {
    "budget_max",
    "exclude_school_ids",
    "add_preferred_city",
    "city_prefs",
    "major_prefs",
    "rejected_majors",
}


class GenerateReportIn(BaseModel):
    profile_id: str
    user_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    thread_id: Optional[str] = None


class GenerateReportOut(BaseModel):
    run_id: str
    status: str
    stream_url: str


class ReportOut(BaseModel):
    id: str
    profile_id: Optional[str]
    run_id: Optional[str]
    status: str
    risk_level: Optional[str]
    risk_score: Optional[float]
    plan_json: Optional[dict]
    evidence_json: Optional[list]
    dataset_version: Optional[str]
    version: int
    parent_report_id: Optional[str]
    run_summary_json: Optional[dict]
    created_at: str


class ReportListItem(BaseModel):
    id: str
    profile_id: Optional[str]
    status: str
    risk_level: Optional[str]
    risk_score: Optional[float]
    dataset_version: Optional[str]
    version: int
    created_at: str


class ReportListOut(BaseModel):
    items: list[ReportListItem]
    next_cursor: Optional[str]
    has_more: bool


def _demo_report_out() -> ReportOut:
    return ReportOut(
        id="demo-report",
        profile_id="demo-profile",
        run_id="demo-run",
        status="completed",
        risk_level="high",
        risk_score=70.0,
        plan_json=MOCK_REPORT_PLAN,
        evidence_json=MOCK_REPORT_EVIDENCE,
        dataset_version="河南_2026_v1",
        version=1,
        parent_report_id=None,
        run_summary_json=None,
        created_at="2026-07-02T10:00:00Z",
    )


def _report_to_out(report: Report) -> ReportOut:
    return ReportOut(
        id=report.id,
        profile_id=report.profile_id,
        run_id=report.run_id,
        status=report.status,
        risk_level=report.risk_level,
        risk_score=report.risk_score,
        plan_json=report.plan_json,
        evidence_json=report.evidence_json,
        dataset_version=report.dataset_version,
        version=report.version,
        parent_report_id=report.parent_report_id,
        run_summary_json=report.run_summary_json,
        created_at=report.created_at.isoformat(),
    )


@router.post("/generate", response_model=GenerateReportOut, status_code=201)
async def generate_report(
    body: GenerateReportIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Semantic entry point for report generation.
    Internally equivalent to POST /agent/runs with task_type=generate_report.
    See PRD 5.1 for the semantic description.
    """
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if not arq_pool:
        raise HTTPException(status_code=503, detail="ARQ pool unavailable")

    thread_id = body.thread_id or str(uuid4())
    run_id = str(uuid4())

    run = AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id=body.user_id,
        anonymous_id=body.anonymous_id,
        profile_id=body.profile_id,
        task_type="generate_report",
        status="queued",
    )
    db.add(run)
    await db.commit()

    # Enqueue to ARQ worker
    await arq_pool.enqueue_job("run_agent", run_id)

    return GenerateReportOut(
        run_id=run_id,
        status="queued",
        stream_url=f"/api/v1/agent/runs/{run_id}/events",
    )


@router.get("", response_model=ReportListOut)
async def list_reports(
    profile_id: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    identity: Identity = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    """
    当前用户（或匿名会话）的报告历史，游标分页 (CLAUDE.md「分页规范」)。
    未登录且无匿名会话 cookie 时返回空列表，而不是全库报告。
    """
    if not identity.user and not identity.anonymous_id:
        return ReportListOut(items=[], next_cursor=None, has_more=False)

    stmt = select(Report).where(Report.deleted_at.is_(None))
    if identity.user:
        stmt = stmt.where(Report.user_id == identity.user.id)
    else:
        stmt = stmt.where(Report.anonymous_id == identity.anonymous_id)
    if profile_id:
        stmt = stmt.where(Report.profile_id == profile_id)

    if cursor:
        try:
            cur_created_at, cur_id = decode_cursor(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid cursor")
        stmt = stmt.where(
            (Report.created_at < cur_created_at)
            | ((Report.created_at == cur_created_at) & (Report.id < cur_id))
        )

    stmt = stmt.order_by(Report.created_at.desc(), Report.id.desc()).limit(limit + 1)

    result = await db.execute(stmt)
    reports = result.scalars().all()
    has_more = len(reports) > limit
    reports = reports[:limit]
    next_cursor = (
        encode_cursor(reports[-1].created_at, reports[-1].id) if has_more and reports else None
    )

    return ReportListOut(
        items=[
            ReportListItem(
                id=r.id,
                profile_id=r.profile_id,
                status=r.status,
                risk_level=r.risk_level,
                risk_score=r.risk_score,
                dataset_version=r.dataset_version,
                version=r.version,
                created_at=r.created_at.isoformat(),
            )
            for r in reports
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/demo-report", response_model=ReportOut)
async def get_demo_report():
    """Static demo report for UI preview and SSE timeout fallback."""
    return _demo_report_out()


@router.get("/by-run/{run_id}", response_model=ReportOut)
async def get_report_by_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch a report by the AgentRun that generated it."""
    if run_id == "demo-run":
        return _demo_report_out()

    result = await db.execute(
        select(Report).where(Report.run_id == run_id, Report.deleted_at.is_(None))
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return _report_to_out(report)


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch a completed Report by ID."""
    if report_id == "demo-report":
        return _demo_report_out()

    result = await db.execute(
        select(Report).where(Report.id == report_id, Report.deleted_at.is_(None))
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="report not found")

    return _report_to_out(report)


# ── 报告局部重新生成 (docs/backend-prd-v2.md §5.9) ────────────────────────────

class RefineIn(BaseModel):
    patch: dict[str, Any]
    source: Optional[str] = None
    conversation_id: Optional[str] = None


class RefineOut(BaseModel):
    parent_report_id: str
    run_id: str
    stream_url: str
    status: str
    estimated_seconds: int


def _build_patched_profile_dict(
    profile: StudentProfile, pref: Optional[Preference], patch: dict[str, Any]
) -> tuple[dict, list[str]]:
    """
    应用 refine patch 到档案字段，返回 (profile_dict, hard_blocked_items)。
    profile_dict 形状与 data_resolver.py 的 _load_profile_sync 保持一致，
    这样 recommendation_agent 复用同一套 profile 读取逻辑无需特殊处理。
    """
    subjects: list[str] = profile.subjects or []
    subject_type = "physics" if "物理" in subjects else "history"

    city_prefs = list(patch.get("city_prefs", (pref.city_prefs if pref else None) or []))
    add_city = patch.get("add_preferred_city")
    if add_city and add_city not in city_prefs:
        city_prefs.append(add_city)

    family_budget = patch.get("budget_max", profile.family_budget)

    profile_dict = {
        "id": profile.id,
        "province": profile.province,
        "score": profile.score or 0,
        "rank": profile.rank or 0,
        "subjects": subjects,
        "subject_type": subject_type,
        "batch": profile.batch or "本科批",
        "family_budget": family_budget,
        "risk_style": profile.risk_style or "balanced",
        "major_prefs": patch.get("major_prefs", (pref.major_prefs if pref else None) or []),
        "city_prefs": city_prefs,
        "rejected_majors": patch.get("rejected_majors", (pref.rejected_majors if pref else None) or []),
    }

    hard_blocked_items = [f"exclude:{sid}" for sid in patch.get("exclude_school_ids", [])]

    return profile_dict, hard_blocked_items


@router.post("/{report_id}/refine", response_model=RefineOut, status_code=202)
async def refine_report(
    report_id: str,
    body: RefineIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    基于约束修改触发局部重新生成，产出新版本报告（parent_report_id 血缘链递增 version）。
    只接受轻量约束 patch（预算/城市偏好/排除院校等）；命中省份/选科/批次等重大约束的字段
    一律返回 422，引导前端走完整的 POST /reports/generate。
    """
    unknown_keys = set(body.patch.keys()) - _LIGHT_PATCH_KEYS
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "requires_full_regenerate",
                    "message": f"以下字段涉及重大约束，需完整重新生成：{', '.join(sorted(unknown_keys))}",
                }
            },
        )

    result = await db.execute(
        select(Report).where(Report.id == report_id, Report.deleted_at.is_(None))
    )
    parent_report = result.scalar_one_or_none()
    if not parent_report:
        raise HTTPException(status_code=404, detail="report not found")

    if not parent_report.profile_id:
        raise HTTPException(status_code=409, detail="checkpoint_not_found")

    profile_result = await db.execute(
        select(StudentProfile).where(StudentProfile.id == parent_report.profile_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=409, detail="checkpoint_not_found")

    pref_result = await db.execute(
        select(Preference).where(Preference.profile_id == parent_report.profile_id)
    )
    pref = pref_result.scalar_one_or_none()

    profile_dict, hard_blocked_items = _build_patched_profile_dict(profile, pref, body.patch)

    arq_pool = getattr(request.app.state, "arq_pool", None)
    if not arq_pool:
        raise HTTPException(status_code=503, detail="ARQ pool unavailable")

    run_id = str(uuid4())
    run = AgentRun(
        id=run_id,
        thread_id=str(uuid4()),
        user_id=parent_report.user_id,
        anonymous_id=parent_report.anonymous_id,
        profile_id=parent_report.profile_id,
        task_type="refine_report",
        status="queued",
    )
    db.add(run)
    await db.commit()

    await arq_pool.enqueue_job("run_refine", run_id, report_id, profile_dict, hard_blocked_items)

    return RefineOut(
        parent_report_id=report_id,
        run_id=run_id,
        stream_url=f"/api/v1/agent/runs/{run_id}/events",
        status="queued",
        estimated_seconds=10,
    )
