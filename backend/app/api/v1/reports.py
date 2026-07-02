from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.mock_data import MOCK_REPORT_EVIDENCE, MOCK_REPORT_PLAN
from app.database import get_db
from app.models.agent_run import AgentRun
from app.models.report import Report

router = APIRouter()


class GenerateReportIn(BaseModel):
    profile_id: str
    user_id: Optional[str] = None
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
    created_at: str


class ReportListItem(BaseModel):
    id: str
    profile_id: Optional[str]
    status: str
    risk_level: Optional[str]
    risk_score: Optional[float]
    dataset_version: Optional[str]
    created_at: str


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


@router.get("", response_model=list[ReportListItem])
async def list_reports(
    profile_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List reports, optionally filtered by profile_id. Ordered by created_at desc."""
    stmt = (
        select(Report)
        .where(Report.deleted_at.is_(None))
        .order_by(Report.created_at.desc())
        .limit(limit)
    )
    if profile_id:
        stmt = stmt.where(Report.profile_id == profile_id)

    result = await db.execute(stmt)
    reports = result.scalars().all()

    return [
        ReportListItem(
            id=r.id,
            profile_id=r.profile_id,
            status=r.status,
            risk_level=r.risk_level,
            risk_score=r.risk_score,
            dataset_version=r.dataset_version,
            created_at=r.created_at.isoformat(),
        )
        for r in reports
    ]


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
