"""
问津 Agent 的 ARQ Worker。
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
from app.prompts import prompt_registry

if settings.langsmith_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

configure_logging()
logger = structlog.get_logger()
prompt_registry.validate_all()


def _checkpoint_dsn() -> str:
    """AsyncPostgresSaver 用的是 psycopg3 驱动，不是 SQLAlchemy 需要的 +asyncpg。"""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def on_startup(ctx: dict) -> None:
    """
    在 worker 进程的整个生命周期内维持一个长连接的 AsyncPostgresSaver 连接池，
    并只编译一次带 checkpoint 的图，这样每次任务调用都基于同一个 checkpointer
    做恢复/持久化，而不是让图状态只存在于内存里（见 docs/memory-architecture.md
    §六 P1 —— 以前 worker 被杀掉/重启后会丢失所有进行中的状态）。
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
    确保图运行结束后前端一定能收到一个终止事件。有两种结局：报告已落库（正常
    路径），或者运行在 PROFILE_CHECK 关卡处停下（profile_agent 分支，见
    graph.py）——这种情况下没有报告产出，但仍要把 SSE 流收尾，而不是让客户端
    一直等一个永远不会到来的 `completed` 事件。
    """
    async with async_session_maker() as db:
        result = await db.execute(
            select(Report).where(Report.run_id == run_id, Report.deleted_at.is_(None))
        )
        report = result.scalar_one_or_none()
        if report:
            report.status = "completed"
            await db.commit()
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
    通过 astream(stream_mode="updates") 驱动传入的已编译图，每完成一个
    superstep 就记一行结构化日志：run_id、node、event、latency_ms。

    `graph` 可能是完整的 `agent_graph`（首次生成），也可能是更小的
    `refine_graph`（只有 recommendation → risk → report → reflection，
    供 /refine 使用——见下面的 run_refine）。

    返回一个 debug_summary 字典，用于写入 agent_runs.debug_summary_json。
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

            # 从 state 增量里收集本轮降级的 agent
            for agent_name in node_state.get("degraded_agents", []):
                if agent_name not in degraded_agents:
                    degraded_agents.append(agent_name)

            # 收集逐次工具调用的日志条目（由 retrieval_agent / policy_rule_agent
            # 写入），供下面聚合成 tool_call_summary。
            tool_call_entries.extend(node_state.get("tool_call_log", []))

            # 业务侧 state_summary 字段，直接从各节点自己的输出增量里读
            # （某个字段只会被拥有它的节点写入）。
            if "evidence_list" in node_state:
                state_summary["evidence_count"] = len(node_state["evidence_list"])
            if "hard_blocked_items" in node_state:
                state_summary["hard_blocked_count"] = len(node_state["hard_blocked_items"])
            if "scored_candidates" in node_state:
                state_summary["candidates_count"] = len(node_state["scored_candidates"])
            if "reflection_iterations" in node_state:
                state_summary["reflection_iterations"] = node_state["reflection_iterations"]

    # 按工具名对 tool_call_entries 分组 → count/success/error/avg_latency_ms
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
        # v1.1 已移除人工复核（HITL，见 CLAUDE.md）——没有任何代码路径会触发
        # human review，所以这里恒为 False 是正确行为，不是占位符。
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
    运行结束后从 LangSmith 读取 token 用量和 trace URL。
    返回 (total_tokens, cost_usd, trace_url)。
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
    Best-effort：把 debug_summary 中对用户安全的一部分，存到这次运行产出的
    Report 上，供报告页"AI 是如何得出这份方案的"决策回放卡片使用
    （docs/backend-prd-v2.md §6.1 reports.run_summary_json）。不含 PII——
    和 Admin Debug 暴露的是同一批字段，只是精简到面向用户回放所需的部分。
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
    首次生成（run_agent）和局部重新生成（run_refine）共用的执行 + 收尾逻辑：
    驱动图运行，写入 AgentRun 的 status/cost/debug_summary，并调用
    `on_success(run_id, debug_summary)` 发送各自类型特有的终止 SSE 事件
    （两者 `completed` 的 payload 结构不同）。

    `graph_input=None` 表示"从这个 thread_id 的最后一个 checkpoint 恢复"
    （见 run_agent 里的 is_resume 判断），而不是重新构造一个全新的
    VolunteerPlanState——剩下的字段由 checkpointer 补全。
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

        # 给 debug summary 补充费用信息
        debug_summary["cost_breakdown"] = {
            "cost_usd": cost_usd,
            "cost_tokens": total_tokens,
        }

        async with async_session_maker() as db2:
            result2 = await db2.execute(select(AgentRun).where(AgentRun.id == run_id))
            run2 = result2.scalar_one_or_none()
            if run2:
                run2.status = "completed"
                # 被恢复的运行可能残留着上一次被中断/超时的尝试留下的
                # error_msg——查看 agent_runs 的人不该看到 status=completed
                # 旁边还挂着上一次失败留下的错误信息。
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

        # asyncio.CancelledError 含义是模糊的：arq 在 job_timeout 超时和
        # worker 进程收到 SIGINT/SIGTERM（优雅关闭/重启）这两种情况下都会抛出
        # 它——以前这两种情况在 agent_runs.status 里无法区分（都是
        # "failed"），导致光看数据库没法回答"这到底是真超时了，还是 worker
        # 刚好被重启了"（docs/memory-architecture.md §六 P1）。耗时接近
        # job_timeout 说明是前者；耗时明显更短说明是外部取消。
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
            report_result = await db3.execute(
                select(Report).where(Report.run_id == run_id, Report.deleted_at.is_(None))
            )
            failed_report = report_result.scalar_one_or_none()
            if failed_report:
                failed_report.status = "failed"
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
    核心 ARQ 任务：从数据库加载 AgentRun，然后走三种行为之一：

    - 恢复（默认，存在 checkpoint）：之前的尝试跑到这一步时被杀掉/取消了——
      从最后完成的节点继续，而不是把整张图重新跑一遍。
    - 全新运行（默认，尚无 checkpoint）：这个 run_id 的第一次调用——构造
      初始 state，从头开始跑。
    - 重试（`force_restart=True`，由 POST .../retry 设置）：即使存在
      checkpoint，也显式丢弃它，从全新的初始 state 重新开始——用于运营
      方想要一次干净的重跑，而不是接着上次失败尝试留下的任意状态继续。

    成功时：把 run 标记为 'completed'，写 completed_at，记录 LangSmith 统计。
    失败时：把 run 标记为 'failed'/'timeout'/'interrupted'，存下 error_msg。
    """
    async with async_session_maker() as db:
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return

        if run.status == "completed" and not force_restart:
            # 幂等保护：重复入队（意外的重复提交，或运营方重试一个已经跑完的
            # run）不能再次执行整张图——否则 report_agent 会给同一个
            # run_id 多插一行 Report。
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
    """ARQ worker 配置。启动方式：arq app.worker.WorkerSettings"""

    functions = [run_agent, run_refine]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 180
