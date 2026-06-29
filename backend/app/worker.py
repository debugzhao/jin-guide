"""
ARQ Worker for 问津 Agent.

This module defines the background task functions executed by ARQ workers.
Run with: arq app.worker.WorkerSettings

See PRD Section 2 for the async task layer architecture:
- Reports are generated via ARQ (not FastAPI BackgroundTasks) for reliability
- LangGraph runs in isolated Worker process
- Progress events written to Redis Stream → consumed by SSE endpoint
"""
import asyncio
from datetime import UTC, datetime

from arq.connections import RedisSettings
from sqlalchemy import select

from app.agent.graph import agent_graph
from app.agent.state import VolunteerPlanState
from app.config import settings
from app.database import async_session_maker
from app.models.agent_run import AgentRun


async def run_agent(ctx: dict, run_id: str) -> None:
    """
    Core ARQ task: load AgentRun from DB, build initial state, invoke LangGraph.

    On success: marks run as 'completed', sets completed_at.
    On failure: marks run as 'failed', stores error_msg.
    """
    async with async_session_maker() as db:
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return

        # Mark as running
        run.status = "running"
        await db.commit()

    # Build initial LangGraph state from the loaded run
    state: VolunteerPlanState = VolunteerPlanState(
        run_id=run.id,
        thread_id=run.thread_id,
        user_id=run.user_id or "",
        profile_id=run.profile_id or "",
        task_type=run.task_type,
        profile=None,
        profile_complete=False,
        profile_pending_questions=[],
        dataset_version=None,
        data_warnings=[],
        evidence_list=[],
        retrieval_complete=False,
        rule_results=[],
        hard_blocked_items=[],
        candidates=[],
        scored_candidates=[],
        tier_summary={},
        risk_items=[],
        overall_risk_level="medium",
        report_draft=None,
        report_id=None,
        compliance_passed=True,
        compliance_issues=[],
        reflection_iterations=0,
        needs_human_review=False,
        review_reasons=[],
        review_task_id=None,
        messages=[],
        started_at=datetime.now(UTC).isoformat(),
        completed_at=None,
        error=None,
        degraded_agents=[],
    )

    try:
        final_state = await agent_graph.ainvoke(state)

        async with async_session_maker() as db2:
            result2 = await db2.execute(
                select(AgentRun).where(AgentRun.id == run_id)
            )
            run2 = result2.scalar_one_or_none()
            if run2:
                run2.status = "completed"
                run2.completed_at = datetime.now(UTC)
                await db2.commit()

    except Exception as exc:
        async with async_session_maker() as db3:
            result3 = await db3.execute(
                select(AgentRun).where(AgentRun.id == run_id)
            )
            run3 = result3.scalar_one_or_none()
            if run3:
                run3.status = "failed"
                run3.error_msg = str(exc)
                run3.completed_at = datetime.now(UTC)
                await db3.commit()
        raise


class WorkerSettings:
    """ARQ worker configuration. Run: arq app.worker.WorkerSettings"""

    functions = [run_agent]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Allow up to 10 concurrent tasks per worker process
    max_jobs = 10
    # Job timeout: 180s (PRD requires 120s auto-timeout; give 60s buffer for cleanup)
    job_timeout = 180
