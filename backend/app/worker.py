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

Day 9 additions:
- Graph execution switched from agent_graph.ainvoke() to consuming
  agent_graph.astream(..., stream_mode="updates"), which yields one chunk per
  completed superstep (a single node, or several nodes that ran in parallel via
  the Send API). This gives per-node visibility for structured logging without
  changing interrupt/exception behavior — interrupt() still raises out of the
  node coroutine the same way whether the graph is driven via ainvoke or astream.
"""
import asyncio
import os
import time
import uuid
from datetime import UTC, datetime

import structlog
from arq.connections import RedisSettings
from sqlalchemy import select

from app.agent.graph import agent_graph, _checkpointer
from app.agent.state import VolunteerPlanState
from app.config import settings
from app.database import async_session_maker
from app.logging_config import configure_logging
from app.models.agent_run import AgentRun

# Must be set before any LangChain client is initialized.
if settings.langsmith_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

configure_logging()
logger = structlog.get_logger()


async def _stream_graph(graph_input, config: dict, run_id: str, phase: str) -> None:
    """
    Drive the graph via astream(stream_mode="updates") and log one structured
    line per completed superstep: run_id, node, event, latency_ms are always
    present so logs can be filtered/aggregated per run or per node.

    `phase` distinguishes the initial run from a post-HITL resume in the logs.
    """
    step_started_at = time.perf_counter()
    async for chunk in agent_graph.astream(graph_input, config=config, stream_mode="updates"):
        latency_ms = round((time.perf_counter() - step_started_at) * 1000, 1)
        step_started_at = time.perf_counter()
        for node_name in chunk:
            logger.info(
                "agent_node_completed",
                run_id=run_id,
                node=node_name,
                event="node_completed",
                phase=phase,
                latency_ms=latency_ms,
            )


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

    run_started_at = time.perf_counter()
    logger.info("agent_run_started", run_id=run_id, node="run", event="run_started", phase="initial")

    try:
        await _stream_graph(state, config, run_id, phase="initial")

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

        logger.info(
            "agent_run_completed",
            run_id=run_id,
            node="run",
            event="run_completed",
            latency_ms=round((time.perf_counter() - run_started_at) * 1000, 1),
        )

    except Exception as exc:
        exc_type = type(exc).__name__
        is_interrupt = exc_type in ("NodeInterrupt", "GraphInterrupt") or (
            hasattr(exc, "__class__") and "Interrupt" in exc_type
        )
        latency_ms = round((time.perf_counter() - run_started_at) * 1000, 1)

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
            logger.info(
                "agent_run_interrupted",
                run_id=run_id,
                node="run",
                event="run_interrupted",
                latency_ms=latency_ms,
            )
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
        logger.warning(
            "agent_run_failed",
            run_id=run_id,
            node="run",
            event="run_failed",
            latency_ms=latency_ms,
            error=str(exc),
        )
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

    resume_started_at = time.perf_counter()
    logger.info("agent_resume_started", run_id=run_id, node="resume", event="resume_started", phase="resume")

    try:
        await _stream_graph(Command(resume=resume_payload), config, run_id, phase="resume")

        async with async_session_maker() as db2:
            result2 = await db2.execute(
                select(AgentRun).where(AgentRun.id == run_id)
            )
            run2 = result2.scalar_one_or_none()
            if run2:
                run2.status = "completed"
                run2.completed_at = datetime.now(UTC)
                await db2.commit()

        logger.info(
            "agent_resume_completed",
            run_id=run_id,
            node="resume",
            event="resume_completed",
            latency_ms=round((time.perf_counter() - resume_started_at) * 1000, 1),
        )

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
        logger.warning(
            "agent_resume_failed",
            run_id=run_id,
            node="resume",
            event="resume_failed",
            latency_ms=round((time.perf_counter() - resume_started_at) * 1000, 1),
            error=str(exc),
        )
        raise


class WorkerSettings:
    """ARQ worker configuration. Run: arq app.worker.WorkerSettings"""

    functions = [run_agent, run_agent_resume]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Allow up to 10 concurrent tasks per worker process
    max_jobs = 10
    # Job timeout: 180s (PRD requires 120s auto-timeout; give 60s buffer for cleanup)
    job_timeout = 180
