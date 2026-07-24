"""
ARQ Worker for 问津 Agent.
"""
import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis
import structlog
from arq.connections import RedisSettings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.agent.graph import create_graph, create_refine_graph
from app.agent.state import VolunteerPlanState
from app.config import settings
from app.database import async_session_maker
from app.logging_config import configure_logging
from app.models.agent_run import AgentRun
from app.models.profile import Preference, StudentProfile
from app.models.report import Report

if settings.langsmith_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

configure_logging()
logger = structlog.get_logger()


def _checkpoint_dsn() -> str:
    """AsyncPostgresSaver uses psycopg3, not the +asyncpg driver SQLAlchemy needs."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def on_startup(ctx: dict) -> None:
    """
    Open one long-lived AsyncPostgresSaver connection pool for the worker
    process's lifetime and compile the checkpointed graphs once, so every
    job invocation resumes/persists against the same checkpointer instead of
    the graph state living only in memory (see docs/memory-architecture.md
    §六 P1 — a killed/restarted worker used to lose all in-flight state).
    """
    checkpointer_cm = AsyncPostgresSaver.from_conn_string(_checkpoint_dsn())
    checkpointer = await checkpointer_cm.__aenter__()
    await checkpointer.setup()
    ctx["checkpointer_cm"] = checkpointer_cm
    ctx["checkpointer"] = checkpointer
    ctx["agent_graph"] = create_graph(checkpointer=checkpointer)
    ctx["refine_graph"] = create_refine_graph(checkpointer=checkpointer)
    logger.info("worker_checkpointer_ready")


async def on_shutdown(ctx: dict) -> None:
    checkpointer_cm = ctx.get("checkpointer_cm")
    if checkpointer_cm:
        await checkpointer_cm.__aexit__(None, None, None)


async def _push_run_sse(run_id: str, event: str, data: dict) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.xadd(
            f"sse:{run_id}",
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
        )
        await redis_client.expire(f"sse:{run_id}", 604800)
    finally:
        await redis_client.aclose()


async def _emit_completed_if_report_exists(run_id: str) -> None:
    """
    Ensure the frontend receives a terminal event once the graph run finishes.
    Two outcomes: a report was persisted (normal path), or the run stopped at
    the PROFILE_CHECK gate (profile_agent branch, see graph.py) — in that case
    there is no report, and we still need to close out the SSE stream instead
    of leaving the client waiting forever for a `completed` event that never comes.
    """
    async with async_session_maker() as db:
        result = await db.execute(
            select(Report).where(Report.run_id == run_id, Report.deleted_at.is_(None))
        )
        report = result.scalar_one_or_none()
        if report:
            await _push_run_sse(run_id, "completed", {
                "report_id": report.id,
                "risk_level": report.risk_level,
                "compliance_passed": True,
            })
            return

        await _push_run_sse(run_id, "profile_incomplete", {
            "message": "档案信息不完整，请补充后重试",
        })


async def _stream_graph(
    graph, graph_input, config: dict, run_id: str
) -> dict:
    """
    Drive the given compiled graph via astream(stream_mode="updates") and log one
    structured line per completed superstep: run_id, node, event, latency_ms.

    `graph` is either the full `agent_graph` (first-time generation) or the
    smaller `refine_graph` (recommendation → risk → report → reflection only,
    used by /refine — see run_refine below).

    Returns a debug_summary dict for writing to agent_runs.debug_summary_json.
    """
    node_timings: dict[str, float] = {}
    degraded_agents: list[str] = []
    tool_call_entries: list[dict] = []
    state_summary: dict = {}
    step_started_at = time.perf_counter()

    async for chunk in graph.astream(graph_input, config=config, stream_mode="updates"):
        latency_ms = round((time.perf_counter() - step_started_at) * 1000, 1)
        step_started_at = time.perf_counter()
        for node_name, node_state in chunk.items():
            node_timings[node_name] = latency_ms
            logger.info(
                "agent_node_completed",
                run_id=run_id,
                node=node_name,
                stage="node_completed",
                latency_ms=latency_ms,
            )
            if not isinstance(node_state, dict):
                continue

            # Collect degraded agents from state delta
            for agent_name in node_state.get("degraded_agents", []):
                if agent_name not in degraded_agents:
                    degraded_agents.append(agent_name)

            # Collect per-tool-call log entries (populated by retrieval_agent /
            # policy_rule_agent) for tool_call_summary aggregation below.
            tool_call_entries.extend(node_state.get("tool_call_log", []))

            # Business state_summary fields, read straight off each node's own
            # output delta (only the node that owns the field ever sets it).
            if "evidence_list" in node_state:
                state_summary["evidence_count"] = len(node_state["evidence_list"])
            if "hard_blocked_items" in node_state:
                state_summary["hard_blocked_count"] = len(node_state["hard_blocked_items"])
            if "scored_candidates" in node_state:
                state_summary["candidates_count"] = len(node_state["scored_candidates"])
            if "reflection_iterations" in node_state:
                state_summary["reflection_iterations"] = node_state["reflection_iterations"]

    # Group tool_call_entries by tool name → count/success/error/avg_latency_ms
    tool_stats: dict[str, dict] = {}
    for entry in tool_call_entries:
        tool = entry.get("tool", "unknown")
        bucket = tool_stats.setdefault(
            tool, {"tool": tool, "count": 0, "success": 0, "error": 0, "_latency_sum": 0.0}
        )
        bucket["count"] += 1
        bucket["_latency_sum"] += entry.get("latency_ms", 0.0)
        if str(entry.get("status", "")).upper() == "ERROR":
            bucket["error"] += 1
        else:
            bucket["success"] += 1

    tool_call_summary = []
    for bucket in tool_stats.values():
        count = bucket["count"]
        tool_call_summary.append({
            "tool": bucket["tool"],
            "count": count,
            "success": bucket["success"],
            "error": bucket["error"],
            "avg_latency_ms": round(bucket["_latency_sum"] / count, 1) if count else 0.0,
        })

    state_summary["nodes_completed"] = list(node_timings.keys())

    return {
        "node_timings": node_timings,
        "tool_call_summary": tool_call_summary,
        "state_summary": state_summary,
        "degraded_agents": degraded_agents,
        # HITL was removed in v1.1 (see CLAUDE.md) — there is no code path that can
        # trigger human review, so this is correctly always False, not a stub.
        "triggered_human_review": False,
    }


def _build_initial_state(run: AgentRun) -> VolunteerPlanState:
    return VolunteerPlanState(
        run_id=run.id,
        thread_id=run.thread_id,
        user_id=run.user_id or "",
        anonymous_id=run.anonymous_id or "",
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
        version=1,
        parent_report_id=None,
        compliance_passed=True,
        compliance_issues=[],
        reflection_iterations=0,
        messages=[],
        started_at=datetime.now(UTC).isoformat(),
        completed_at=None,
        error=None,
        degraded_agents=[],
        tool_call_log=[],
    )


def _build_refine_state(
    run: AgentRun, parent_report: Report, profile_dict: dict, hard_blocked_items: list[str]
) -> VolunteerPlanState:
    """
    局部重新生成的初始 state：复用被 refine 报告的 evidence_json（不重新检索/校验规则），
    profile 已经在调用方（run_refine）应用过 patch。
    """
    return VolunteerPlanState(
        run_id=run.id,
        thread_id=run.thread_id,
        user_id=run.user_id or "",
        anonymous_id=run.anonymous_id or "",
        profile_id=run.profile_id or "",
        task_type=run.task_type,
        profile=profile_dict,
        profile_complete=True,
        profile_pending_questions=[],
        dataset_version=parent_report.dataset_version,
        data_warnings=[],
        evidence_list=parent_report.evidence_json or [],
        retrieval_complete=True,
        rule_results=[],
        hard_blocked_items=hard_blocked_items,
        candidates=[],
        scored_candidates=[],
        tier_summary={},
        risk_items=[],
        overall_risk_level="medium",
        report_draft=None,
        report_id=None,
        version=(parent_report.version or 1) + 1,
        parent_report_id=parent_report.id,
        compliance_passed=True,
        compliance_issues=[],
        reflection_iterations=0,
        messages=[],
        started_at=datetime.now(UTC).isoformat(),
        completed_at=None,
        error=None,
        degraded_agents=[],
        tool_call_log=[],
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


async def _write_run_summary_to_report(run_id: str, debug_summary: dict) -> None:
    """
    Best-effort: stash a user-safe subset of debug_summary on the Report this run
    produced, for the report page's "AI 是如何得出这份方案的" decision replay card
    (docs/backend-prd-v2.md §6.1 reports.run_summary_json). No PII — same fields
    already exposed to Admin Debug, just trimmed to what a user-facing replay needs.
    """
    summary = {
        "node_timings": debug_summary.get("node_timings", {}),
        "degraded_agents": debug_summary.get("degraded_agents", []),
        "reflection_iterations": debug_summary.get("state_summary", {}).get("reflection_iterations", 0),
    }
    async with async_session_maker() as db:
        result = await db.execute(
            select(Report).where(Report.run_id == run_id, Report.deleted_at.is_(None))
        )
        report = result.scalar_one_or_none()
        if report:
            report.run_summary_json = summary
            await db.commit()


async def _run_graph_and_finalize(
    *,
    graph,
    graph_input: VolunteerPlanState | None,
    run: AgentRun,
    on_success,
) -> None:
    """
    Shared execution + finalization for both first-time generation (run_agent)
    and local refine (run_refine): drive the graph, write AgentRun status/cost/
    debug_summary, and call `on_success(run_id, debug_summary)` for the
    run-type-specific terminal SSE event (their `completed` payload shapes differ).

    `graph_input=None` means "resume from the last checkpoint for this
    thread_id" (see run_agent's is_resume check) instead of starting a fresh
    VolunteerPlanState — the checkpointer fills in the rest.
    """
    run_id = run.id
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
    logger.info("agent_run_started", run_id=run_id, node="run", stage="run_started")

    try:
        debug_summary = await _stream_graph(graph, graph_input, config, run_id)
        await on_success(run_id, debug_summary)

        total_tokens, cost_usd, trace_url = _get_langsmith_stats(ls_run_id)
        duration_seconds = round(time.perf_counter() - run_started_at, 2)

        # Enrich debug summary with cost info
        debug_summary["cost_breakdown"] = {
            "cost_usd": cost_usd,
            "cost_tokens": total_tokens,
        }

        async with async_session_maker() as db2:
            result2 = await db2.execute(select(AgentRun).where(AgentRun.id == run_id))
            run2 = result2.scalar_one_or_none()
            if run2:
                run2.status = "completed"
                # A resumed run may carry a stale error_msg from the attempt
                # that got interrupted/timed out before this one — a reader
                # of agent_runs shouldn't see status=completed next to a
                # leftover failure message from a previous try.
                run2.error_msg = None
                run2.completed_at = datetime.now(UTC)
                run2.cost_tokens = total_tokens
                run2.cost_usd = cost_usd
                run2.trace_url = trace_url
                run2.duration_seconds = duration_seconds
                run2.debug_summary_json = debug_summary
                await db2.commit()

        await _write_run_summary_to_report(run_id, debug_summary)

        logger.info(
            "agent_run_completed",
            run_id=run_id,
            node="run",
            stage="run_completed",
            latency_ms=round(duration_seconds * 1000, 1),
        )

    except (Exception, asyncio.CancelledError) as exc:
        duration_seconds = round(time.perf_counter() - run_started_at, 2)
        latency_ms = round(duration_seconds * 1000, 1)

        # asyncio.CancelledError is ambiguous: arq raises it both when
        # job_timeout is exceeded AND when the worker process receives
        # SIGINT/SIGTERM (graceful shutdown/restart) — these used to be
        # indistinguishable in agent_runs.status (both "failed"), which made
        # "did this actually time out or did the worker just get restarted"
        # unanswerable from the DB alone (docs/memory-architecture.md §六 P1).
        # Elapsed time close to job_timeout implies the former; a much
        # shorter elapsed time implies external cancellation.
        if isinstance(exc, asyncio.CancelledError):
            if duration_seconds >= WorkerSettings.job_timeout - 1:
                new_status = "timeout"
                error_msg = f"job cancelled (job_timeout={WorkerSettings.job_timeout}s exceeded)"
            else:
                new_status = "interrupted"
                error_msg = "job cancelled before job_timeout — worker likely shutting down/restarting"
        else:
            new_status = "failed"
            error_msg = str(exc) or repr(exc)

        async with async_session_maker() as db3:
            result3 = await db3.execute(select(AgentRun).where(AgentRun.id == run_id))
            run3 = result3.scalar_one_or_none()
            if run3:
                run3.status = new_status
                run3.error_msg = error_msg
                run3.completed_at = datetime.now(UTC)
                run3.duration_seconds = duration_seconds
                await db3.commit()
        logger.warning(
            "agent_run_failed",
            run_id=run_id,
            node="run",
            stage="run_failed",
            status=new_status,
            latency_ms=latency_ms,
            error=error_msg,
        )
        raise


async def run_agent(ctx: dict, run_id: str, force_restart: bool = False) -> None:
    """
    Core ARQ task: load AgentRun from DB, then pick one of three behaviors:

    - Resume (default, checkpoint exists): a previous attempt got this far
      and was killed/cancelled before finishing — continue from the last
      completed node instead of re-running the whole graph.
    - Fresh run (default, no checkpoint yet): first-ever invocation for this
      run_id — build the initial state and run from the top.
    - Retry (`force_restart=True`, set by POST .../retry): explicitly discard
      any existing checkpoint and start over from a fresh initial state, even
      if one exists — for when the operator wants a clean re-run rather than
      continuing from whatever state a failed attempt left behind.

    On success: marks run as 'completed', sets completed_at, writes LangSmith stats.
    On failure: marks run as 'failed'/'timeout'/'interrupted', stores error_msg.
    """
    async with async_session_maker() as db:
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return

        if run.status == "completed" and not force_restart:
            # Idempotency guard: a duplicate enqueue (accidental double-submit,
            # or an operator retrying an already-finished run) must not
            # re-execute the graph — report_agent would otherwise mint a
            # second Report row for the same run_id.
            logger.info("agent_run_already_completed_skip", run_id=run_id)
            return

        run.status = "running"
        run.error_msg = None
        await db.commit()

    checkpointer = ctx["checkpointer"]
    thread_config = {"configurable": {"thread_id": run.thread_id}}
    if force_restart:
        await checkpointer.adelete_thread(run.thread_id)
        graph_input = _build_initial_state(run)
    else:
        existing_checkpoint = await checkpointer.aget_tuple(thread_config)
        graph_input = None if existing_checkpoint else _build_initial_state(run)

    async def on_success(rid: str, _debug_summary: dict) -> None:
        await _emit_completed_if_report_exists(rid)

    await _run_graph_and_finalize(
        graph=ctx["agent_graph"], graph_input=graph_input, run=run, on_success=on_success
    )


async def run_refine(
    ctx: dict,
    run_id: str,
    parent_report_id: str,
    profile_dict: dict,
    hard_blocked_items: list[str],
) -> None:
    """
    局部重新生成 (docs/backend-prd-v2.md §5.9)：只重跑
    recommendation → risk → report → reflection，复用 parent_report.evidence_json。
    `profile_dict`/`hard_blocked_items` 已经在 POST /reports/{id}/refine 里把 patch
    应用好，这里不再重新查一次 DB 或解析 patch。
    """
    async with async_session_maker() as db:
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return

        if run.status == "completed":
            logger.info("agent_run_already_completed_skip", run_id=run_id)
            return

        run.status = "running"
        await db.commit()

        parent_result = await db.execute(
            select(Report).where(Report.id == parent_report_id, Report.deleted_at.is_(None))
        )
        parent_report = parent_result.scalar_one_or_none()
        if not parent_report:
            run.status = "failed"
            run.error_msg = "parent report not found"
            run.completed_at = datetime.now(UTC)
            await db.commit()
            return

    checkpointer = ctx["checkpointer"]
    thread_config = {"configurable": {"thread_id": run.thread_id}}
    existing_checkpoint = await checkpointer.aget_tuple(thread_config)
    graph_input = (
        None if existing_checkpoint
        else _build_refine_state(run, parent_report, profile_dict, hard_blocked_items)
    )

    async def on_success(rid: str, _debug_summary: dict) -> None:
        async with async_session_maker() as db2:
            r = await db2.execute(
                select(Report).where(Report.run_id == rid, Report.deleted_at.is_(None))
            )
            new_report = r.scalar_one_or_none()
        if not new_report:
            return
        await _push_run_sse(rid, "completed", {
            "report_id": new_report.id,
            "parent_report_id": parent_report_id,
            "version": new_report.version,
            "diff_summary": {
                "candidates_before": len((parent_report.plan_json or {}).get("balanced", {}).get("volunteers", [])),
                "candidates_after": len((new_report.plan_json or {}).get("balanced", {}).get("volunteers", [])),
            },
        })

    await _run_graph_and_finalize(
        graph=ctx["refine_graph"], graph_input=graph_input, run=run, on_success=on_success
    )


class WorkerSettings:
    """ARQ worker configuration. Run: arq app.worker.WorkerSettings"""

    functions = [run_agent, run_refine]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 180
