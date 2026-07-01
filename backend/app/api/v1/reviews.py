"""
Human Review API (Day 8-9).

Endpoints:
  GET    /api/v1/reviews                — list reviews (reviewer queue / by report_id)
  POST   /api/v1/reviews                — user-initiated review request (no active interrupt)
  GET    /api/v1/reviews/{id}           — get single review + checklist
  PATCH  /api/v1/reviews/{id}           — submit conclusion, trigger resume

PRD references: Section 11.2 (interrupt mechanism), 11.7 (resume payload), 8.7 (user-facing review page).
"""
from __future__ import annotations

import structlog
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.agent_run import AgentRun
from app.models.report import Report
from app.models.review import HumanReview

logger = structlog.get_logger()

# Same SLA window used by the interrupt-triggered review node (backend/app/agent/nodes/human_review.py)
_REVIEW_SLA_HOURS = 4


def _write_langsmith_feedback(trace_url: str, conclusion: str, notes: str | None) -> None:
    """
    Write human review conclusion as LangSmith feedback.
    Fire-and-forget: errors are logged but never propagate to the caller.

    trace_url format: https://smith.langchain.com/o/.../runs/{ls_run_id}
    score convention: 1.0 = approved, 0.0 = rejected
    """
    if not settings.langsmith_api_key or not trace_url:
        return
    try:
        from langsmith import Client
        ls_run_id = trace_url.rstrip("/").split("/")[-1]
        client = Client(api_key=settings.langsmith_api_key)
        client.create_feedback(
            run_id=ls_run_id,
            key="human_review_conclusion",
            score=1.0 if conclusion == "approved" else 0.0,
            comment=notes or "",
        )
    except Exception as exc:
        logger.warning("langsmith_feedback_failed", trace_url=trace_url, error=str(exc))

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class ReviewOut(BaseModel):
    id: str
    report_id: Optional[str]
    run_id: Optional[str]
    reviewer_id: Optional[str]
    status: str
    checklist_json: Optional[dict]
    conclusion: Optional[str]
    reviewer_notes: Optional[str]
    created_at: str
    completed_at: Optional[str]
    timeout_at: Optional[str]


class ReviewListItem(BaseModel):
    id: str
    report_id: Optional[str]
    run_id: Optional[str]
    status: str
    conclusion: Optional[str]
    created_at: str
    timeout_at: Optional[str]


class CreateReviewIn(BaseModel):
    report_id: str
    reason: Optional[str] = None


class ClaimReviewIn(BaseModel):
    reviewer_id: str


class SubmitConclusionIn(BaseModel):
    # approved / rejected / need_more_info
    conclusion: str
    reviewer_id: Optional[str] = None
    reviewer_notes: Optional[str] = None
    # Override risk level (optional, reviewer can downgrade)
    override_risk_level: Optional[str] = None
    # Per-checklist-item verdicts
    checklist_results: Optional[list[dict]] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ReviewListItem])
async def list_reviews(
    status: Optional[str] = Query(None, description="Filter by status (pending / in_review / reviewed)"),
    report_id: Optional[str] = Query(None, description="Filter by report_id (user-side lookup)"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List human reviews, ordered by created_at asc (oldest pending first)."""
    stmt = (
        select(HumanReview)
        .order_by(HumanReview.created_at.asc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(HumanReview.status == status)
    if report_id:
        stmt = stmt.where(HumanReview.report_id == report_id)

    result = await db.execute(stmt)
    reviews = result.scalars().all()

    return [
        ReviewListItem(
            id=r.id,
            report_id=r.report_id,
            run_id=r.run_id,
            status=r.status,
            conclusion=r.conclusion,
            created_at=r.created_at.isoformat(),
            timeout_at=r.timeout_at.isoformat() if r.timeout_at else None,
        )
        for r in reviews
    ]


@router.post("", response_model=ReviewOut)
async def create_review(
    body: CreateReviewIn,
    db: AsyncSession = Depends(get_db),
):
    """
    User-initiated review request (PRD 8.7 "用户也可主动点击...申请人工复核").

    Unlike the interrupt-triggered flow in human_review_node, this does not pause
    a running graph — the report already exists and was delivered normally.
    Submitting a conclusion for this review later will not attempt to resume a
    graph run, since PATCH /reviews/{id} only enqueues a resume job when
    review.run_id is set AND the graph is actually paused there.
    """
    report_result = await db.execute(select(Report).where(Report.id == body.report_id))
    report = report_result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="report not found")

    # Idempotent: reuse an existing open review instead of creating duplicates
    existing_result = await db.execute(
        select(HumanReview)
        .where(HumanReview.report_id == body.report_id)
        .where(HumanReview.status.notin_(["reviewed", "closed"]))
        .order_by(HumanReview.created_at.desc())
        .limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return ReviewOut(
            id=existing.id,
            report_id=existing.report_id,
            run_id=existing.run_id,
            reviewer_id=existing.reviewer_id,
            status=existing.status,
            checklist_json=existing.checklist_json,
            conclusion=existing.conclusion,
            reviewer_notes=existing.reviewer_notes,
            created_at=existing.created_at.isoformat(),
            completed_at=existing.completed_at.isoformat() if existing.completed_at else None,
            timeout_at=existing.timeout_at.isoformat() if existing.timeout_at else None,
        )

    plan_json = report.plan_json or {}
    # plan_json.risk_items uses {level, description} (see report_agent.py); the
    # review checklist schema uses {risk_type, severity, targets, message} — convert.
    risk_items = [
        {
            "risk_type": r.get("risk_type", "general"),
            "severity": r.get("level", "medium"),
            "targets": r.get("targets", []),
            "message": r.get("description", ""),
        }
        for r in (plan_json.get("risk_items") or [])
    ]
    summary = body.reason or "用户主动申请人工复核。"

    now = datetime.now(UTC)
    review = HumanReview(
        id=str(uuid4()),
        report_id=report.id,
        run_id=report.run_id,
        status="pending",
        checklist_json={
            "summary": summary,
            "trigger_reasons": ["user_requested"],
            "risk_items": risk_items,
            "compliance_issues": [],
            "data_warnings": [],
            "reviewer_checklist": [
                {"id": "c1", "item": "复核用户提出的具体疑虑", "required": True},
            ],
        },
        timeout_at=now + timedelta(hours=_REVIEW_SLA_HOURS),
    )
    db.add(review)
    await db.commit()

    return ReviewOut(
        id=review.id,
        report_id=review.report_id,
        run_id=review.run_id,
        reviewer_id=review.reviewer_id,
        status=review.status,
        checklist_json=review.checklist_json,
        conclusion=review.conclusion,
        reviewer_notes=review.reviewer_notes,
        created_at=review.created_at.isoformat(),
        completed_at=None,
        timeout_at=review.timeout_at.isoformat() if review.timeout_at else None,
    )


@router.get("/{review_id}", response_model=ReviewOut)
async def get_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single review by ID, including the full checklist_json."""
    result = await db.execute(
        select(HumanReview).where(HumanReview.id == review_id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="review not found")

    return ReviewOut(
        id=review.id,
        report_id=review.report_id,
        run_id=review.run_id,
        reviewer_id=review.reviewer_id,
        status=review.status,
        checklist_json=review.checklist_json,
        conclusion=review.conclusion,
        reviewer_notes=review.reviewer_notes,
        created_at=review.created_at.isoformat(),
        completed_at=review.completed_at.isoformat() if review.completed_at else None,
        timeout_at=review.timeout_at.isoformat() if review.timeout_at else None,
    )


@router.patch("/{review_id}/claim", response_model=ReviewOut)
async def claim_review(
    review_id: str,
    body: ClaimReviewIn,
    db: AsyncSession = Depends(get_db),
):
    """
    Reviewer claims a pending review (复核员工作台 "领取任务").

    Only 'pending' reviews can be claimed. Re-claiming by the same reviewer
    is idempotent (e.g. page refresh); claiming by a different reviewer while
    already 'in_review' is rejected to avoid two reviewers working the same task.
    """
    result = await db.execute(
        select(HumanReview).where(HumanReview.id == review_id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="review not found")

    if review.status == "in_review" and review.reviewer_id == body.reviewer_id:
        pass  # idempotent re-claim
    elif review.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"review is not claimable (status='{review.status}')",
        )
    else:
        review.status = "in_review"
        review.reviewer_id = body.reviewer_id
        await db.commit()

    return ReviewOut(
        id=review.id,
        report_id=review.report_id,
        run_id=review.run_id,
        reviewer_id=review.reviewer_id,
        status=review.status,
        checklist_json=review.checklist_json,
        conclusion=review.conclusion,
        reviewer_notes=review.reviewer_notes,
        created_at=review.created_at.isoformat(),
        completed_at=review.completed_at.isoformat() if review.completed_at else None,
        timeout_at=review.timeout_at.isoformat() if review.timeout_at else None,
    )


@router.patch("/{review_id}", response_model=ReviewOut)
async def submit_conclusion(
    review_id: str,
    body: SubmitConclusionIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit review conclusion (approved / rejected / need_more_info).

    On approved/rejected:
      - Updates HumanReview status → 'reviewed'
      - Updates AgentRun status → 'running' (resume pending)
      - Enqueues run_agent_resume ARQ job with conclusion payload
    On need_more_info:
      - Sets status → 'need_more_info', does NOT resume graph
    """
    result = await db.execute(
        select(HumanReview).where(HumanReview.id == review_id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="review not found")

    if review.status in ("reviewed", "closed"):
        raise HTTPException(
            status_code=409, detail=f"review already in status '{review.status}'"
        )

    valid_conclusions = ("approved", "rejected", "need_more_info")
    if body.conclusion not in valid_conclusions:
        raise HTTPException(
            status_code=422,
            detail=f"conclusion must be one of {valid_conclusions}",
        )

    # Update HumanReview record
    review.conclusion = body.conclusion
    review.reviewer_id = body.reviewer_id
    review.reviewer_notes = body.reviewer_notes

    if body.conclusion == "need_more_info":
        review.status = "need_more_info"
        await db.commit()
        return ReviewOut(
            id=review.id,
            report_id=review.report_id,
            run_id=review.run_id,
            reviewer_id=review.reviewer_id,
            status=review.status,
            checklist_json=review.checklist_json,
            conclusion=review.conclusion,
            reviewer_notes=review.reviewer_notes,
            created_at=review.created_at.isoformat(),
            completed_at=None,
            timeout_at=review.timeout_at.isoformat() if review.timeout_at else None,
        )

    # approved or rejected — trigger resume
    review.status = "reviewed"
    review.completed_at = datetime.now(UTC)
    await db.commit()

    # Write human verdict to LangSmith for quality tracking (non-blocking)
    if review.run_id:
        run_result = await db.execute(select(AgentRun).where(AgentRun.id == review.run_id))
        agent_run = run_result.scalar_one_or_none()
        if agent_run and agent_run.trace_url:
            _write_langsmith_feedback(agent_run.trace_url, body.conclusion, body.reviewer_notes)

    # Build resume payload (injected into State.messages as HumanMessage)
    resume_payload: dict[str, Any] = {
        "review_conclusion": body.conclusion,
        "reviewer_id": body.reviewer_id,
        "reviewer_notes": body.reviewer_notes,
        "checklist_results": body.checklist_results or [],
    }
    if body.override_risk_level:
        resume_payload["override_risk_level"] = body.override_risk_level

    # Enqueue resume job in ARQ
    if review.run_id:
        arq_pool = getattr(request.app.state, "arq_pool", None)
        if arq_pool:
            await arq_pool.enqueue_job("run_agent_resume", review.run_id, resume_payload)
        else:
            raise HTTPException(
                status_code=503, detail="ARQ pool unavailable — cannot resume run"
            )

    return ReviewOut(
        id=review.id,
        report_id=review.report_id,
        run_id=review.run_id,
        reviewer_id=review.reviewer_id,
        status=review.status,
        checklist_json=review.checklist_json,
        conclusion=review.conclusion,
        reviewer_notes=review.reviewer_notes,
        created_at=review.created_at.isoformat(),
        completed_at=review.completed_at.isoformat() if review.completed_at else None,
        timeout_at=review.timeout_at.isoformat() if review.timeout_at else None,
    )
