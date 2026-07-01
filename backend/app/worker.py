"""
ARQ Worker for 问津 Agent.

This module defines the background task functions executed by ARQ workers.
Run with: arq app.worker.WorkerSettings

See PRD Section 2 for the async task layer architecture:
- Reports are generated via ARQ (not FastAPI BackgroundTasks) for reliability
- LangGraph runs in isolated Worker process
- Progress events written to Redis Stream → consumed by SSE endpoint

Day 8 additions:
- run_agent now catches NodeInterrupt → marks run as 'interrupted'
- run_agent_resume: resumes an interrupted run via Command(resume=payload)
"""
import asyncio
import os
import uuid
from datetime import UTC, datetime

from arq.connections import RedisSettings
from sqlalchemy import select

from app.agent.graph import agent_graph, _checkpointer
from app.agent.state import VolunteerPlanState
from app.config import settings
from app.database import async_session_maker
from app.models.agent_run import AgentRun

# Must be set before any LangChain client is initialized.
if settings.langsmith_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project


def _build_initial_state(run: AgentRun) -> VolunteerPlanState:
    return VolunteerPlanState(
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


def _get_langsmith_stats(ls_run_id: uuid.UUID) -> tuple[int, float, str | None]:
    """
    Read token usage and trace URL from LangSmith after a run completes.

    Returns (total_tokens, cost_usd, trace_url).
    Returns zeros and None if LangSmith is not configured or the run is not found.
    """
    if not settings.langsmith_api_key:
        return 0, 0.0, None

    try:
        from langsmith import Client

        client = Client(api_key=settings.langsmith_api_key)
        ls_run = client.read_run(str(ls_run_id))
        total_tokens = (ls_run.total_tokens or 0)
        # LangSmith stores cost in prompt_cost + completion_cost (USD)
        cost_usd = (ls_run.prompt_cost or 0.0) + (ls_run.completion_cost or 0.0)
        trace_url = ls_run.url
        return total_tokens, cost_usd, trace_url
    except Exception:
        return 0, 0.0, None


async def run_agent(ctx: dict, run_id: str) -> None:
    """
    Core ARQ task: load AgentRun from DB, build initial state, invoke LangGraph.

    On success: marks run as 'completed', sets completed_at, writes LangSmith stats.
    On interrupt (NodeInterrupt): marks run as 'interrupted' (awaiting human review).
    On failure: marks run as 'failed', stores error_msg.
    """
    async with async_session_maker() as db:
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return

        run.status = "running"
        await db.commit()

    state = _build_initial_state(run)

    # Pin a deterministic LangSmith run_id so we can look it up after execution.
    ls_run_id = uuid.uuid4()
    config = {
        "configurable": {"thread_id": run.thread_id},
        "run_id": ls_run_id,
        # Tags and metadata are indexed in LangSmith and filterable in the dashboard.
        "tags": [run.task_type, settings.env],
        "metadata": {
            "run_id": run_id,
            "user_id": run.user_id or "",
            "profile_id": run.profile_id or "",
            "task_type": run.task_type,
        },
    }

    try:
        await agent_graph.ainvoke(state, config=config)

        total_tokens, cost_usd, trace_url = _get_langsmith_stats(ls_run_id)

        async with async_session_maker() as db2:
            result2 = await db2.execute(
                select(AgentRun).where(AgentRun.id == run_id)
            )
            run2 = result2.scalar_one_or_none()
            if run2:
                run2.status = "completed"
                run2.completed_at = datetime.now(UTC)
                run2.cost_tokens = total_tokens
                run2.cost_usd = cost_usd
                run2.trace_url = trace_url
                await db2.commit()

    except Exception as exc:
        exc_type = type(exc).__name__
        is_interrupt = exc_type in ("NodeInterrupt", "GraphInterrupt") or (
            hasattr(exc, "__class__") and "Interrupt" in exc_type
        )

        if is_interrupt:
            _, _, trace_url = _get_langsmith_stats(ls_run_id)
            async with async_session_maker() as db3:
                result3 = await db3.execute(
                    select(AgentRun).where(AgentRun.id == run_id)
                )
                run3 = result3.scalar_one_or_none()
                if run3:
                    run3.status = "interrupted"
                    run3.trace_url = trace_url
                    await db3.commit()
            return

        async with async_session_maker() as db4:
            result4 = await db4.execute(
                select(AgentRun).where(AgentRun.id == run_id)
            )
            run4 = result4.scalar_one_or_none()
            if run4:
                run4.status = "failed"
                run4.error_msg = str(exc)
                run4.completed_at = datetime.now(UTC)
                await db4.commit()
        raise


async def run_agent_resume(ctx: dict, run_id: str, resume_payload: dict) -> None:
    """
    Resume an interrupted AgentRun after human review.

    Injects the review conclusion into the graph via Command(resume=payload)
    using the same thread_id config so LangGraph checkpointer restores state.

    PRD reference: Section 11.7 (resume payload) and 11.2 (interrupt mechanism).
    """
    from langgraph.types import Command

    async with async_session_maker() as db:
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return

        run.status = "running"
        await db.commit()

    config = {"configurable": {"thread_id": run.thread_id}}

    try:
        await agent_graph.ainvoke(Command(resume=resume_payload), config=config)

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
                run3.error_msg = f"resume failed: {exc!s}"
                run3.completed_at = datetime.now(UTC)
                await db3.commit()
        raise


class WorkerSettings:
    """ARQ worker configuration. Run: arq app.worker.WorkerSettings"""

    functions = [run_agent, run_agent_resume]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Allow up to 10 concurrent tasks per worker process
    max_jobs = 10
    # Job timeout: 180s (PRD requires 120s auto-timeout; give 60s buffer for cleanup)
    job_timeout = 180
