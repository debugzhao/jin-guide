"""
ARQ Worker for 问津 Agent.

This module defines the background task functions executed by ARQ workers.
Run with: arq app.worker.WorkerSettings

Architecture:
- Reports are generated via ARQ (not FastAPI BackgroundTasks) for reliability
- LangGraph runs in isolated Worker process
- Progress events written to Redis Stream → consumed by SSE endpoint
- Graph execution uses astream(stream_mode="updates") for per-node structured logging
"""
import os
import time
import uuid
from datetime import UTC, datetime

import structlog
from arq.connections import RedisSettings
from sqlalchemy import select

from app.agent.graph import agent_graph
from app.agent.state import VolunteerPlanState
from app.config import settings
from app.database import async_session_maker
from app.logging_config import configure_logging
from app.models.agent_run import AgentRun

if settings.langsmith_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

configure_logging()
logger = structlog.get_logger()


async def _stream_graph(graph_input, config: dict, run_id: str) -> None:
    """
    Drive the graph via astream(stream_mode="updates") and log one structured
    line per completed superstep: run_id, node, event, latency_ms.
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
    """
    if not settings.langsmith_api_key:
        return 0, 0.0, None

    try:
        from langsmith import Client

        client = Client(api_key=settings.langsmith_api_key)
        ls_run = client.read_run(str(ls_run_id))
        total_tokens = ls_run.total_tokens or 0
        cost_usd = (ls_run.prompt_cost or 0.0) + (ls_run.completion_cost or 0.0)
        return total_tokens, cost_usd, ls_run.url
    except Exception:
        return 0, 0.0, None


async def run_agent(ctx: dict, run_id: str) -> None:
    """
    Core ARQ task: load AgentRun from DB, build initial state, invoke LangGraph.

    On success: marks run as 'completed', sets completed_at, writes LangSmith stats.
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

    ls_run_id = uuid.uuid4()
    config = {
        "configurable": {"thread_id": run.thread_id},
        "run_id": ls_run_id,
        "tags": [run.task_type, settings.env],
        "metadata": {
            "run_id": run_id,
            "user_id": run.user_id or "",
            "profile_id": run.profile_id or "",
            "task_type": run.task_type,
        },
    }

    run_started_at = time.perf_counter()
    logger.info("agent_run_started", run_id=run_id, node="run", event="run_started")

    try:
        await _stream_graph(state, config, run_id)

        total_tokens, cost_usd, trace_url = _get_langsmith_stats(ls_run_id)

        async with async_session_maker() as db2:
            result2 = await db2.execute(select(AgentRun).where(AgentRun.id == run_id))
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
        latency_ms = round((time.perf_counter() - run_started_at) * 1000, 1)
        async with async_session_maker() as db3:
            result3 = await db3.execute(select(AgentRun).where(AgentRun.id == run_id))
            run3 = result3.scalar_one_or_none()
            if run3:
                run3.status = "failed"
                run3.error_msg = str(exc)
                run3.completed_at = datetime.now(UTC)
                await db3.commit()
        logger.warning(
            "agent_run_failed",
            run_id=run_id,
            node="run",
            event="run_failed",
            latency_ms=latency_ms,
            error=str(exc),
        )
        raise


class WorkerSettings:
    """ARQ worker configuration. Run: arq app.worker.WorkerSettings"""

    functions = [run_agent]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 180
