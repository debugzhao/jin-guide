"""
问津 Agent 的 LangGraph 状态机。

图拓扑结构：

    data_resolver
      [PROFILE_CHECK: 档案完整？]
       /              \\
  profile_agent    retrieval_agent  policy_rule_agent   (parallel fan-out)
      |                    \\        /
     END                 recommendation
                               |
                              risk
                               |
                             report
                               |
                           reflection  ←──── (retry loop, max 3 iterations)
                               |
                         [conditional]
                            /    \\
                         END    report (retry when compliance issues)

data_resolver 之后的条件路由（PROFILE_CHECK）：
  profile_complete       → [retrieval_agent, policy_rule_agent]（并行 fan-out）
  NOT profile_complete   → profile_agent (追问，不生成报告，图在此结束)

reflection 之后的条件路由：
  compliance_passed                    → END
  NOT compliance_passed AND iter < 3  → report（重试）
  max iterations exceeded              → END（尽力交付）
"""
import time
from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.debug_events import emit_debug_event
from app.agent.nodes.data_resolver import data_resolver
from app.agent.nodes.policy_rule_agent import policy_rule_agent
from app.agent.nodes.profile_agent import profile_agent
from app.agent.nodes.recommendation_agent import recommendation_agent
from app.agent.nodes.reflection_agent import reflection_agent
from app.agent.nodes.report_agent import report_agent
from app.agent.nodes.retrieval_agent import retrieval_agent
from app.agent.nodes.risk import risk_node
from app.agent.state import VolunteerPlanState
from app.agent.user_events import push_user_event

_MAX_REFLECTION_ITERATIONS = 3

# data_resolver 之后并行运行的节点（顺序即 SSE agents_parallel_started
# 事件里 "agents" 字段的顺序，对齐 docs/backend-prd-v2.md §5.7 示例）
_PARALLEL_NODES = ("retrieval_agent", "policy_rule_agent")
# 合并两个并行分支的节点
_FAN_IN_NODE = "recommendation"


def _wrap_with_debug(node_name: str, fn: Callable) -> Callable:
    """
    包装 LangGraph 节点函数，在其执行前后发出 debug:node_started /
    debug:node_completed 事件。

    另外在 data_resolver 完成时发出 debug:parallel_fan_out，
    在合并节点（recommendation）开始时发出 debug:parallel_fan_in。
    """

    async def _wrapped(state: VolunteerPlanState) -> Any:
        run_id: str = state.get("run_id", "")
        t0 = time.perf_counter()

        # fan-out 标记：仅在 data_resolver 完成时触发一次
        if node_name == "data_resolver":
            await emit_debug_event(
                run_id,
                "node_started",
                {"node": node_name, "status": "running"},
            )

        elif node_name in _PARALLEL_NODES:
            await emit_debug_event(
                run_id,
                "parallel_fan_out",
                {"node": node_name, "from": "data_resolver"},
            )
            await emit_debug_event(
                run_id,
                "node_started",
                {"node": node_name, "status": "running"},
            )
            # 两个并行节点同时进图，只从其中一个（约定用列表里的第一个）广播一次
            # 用户侧的 agents_parallel_started，避免重复推送两条一样的事件。
            if node_name == _PARALLEL_NODES[0]:
                await push_user_event(
                    run_id,
                    "agents_parallel_started",
                    {
                        "agents": list(_PARALLEL_NODES),
                        "message": "正在同时检索数据和校验规则",
                    },
                )

        elif node_name == _FAN_IN_NODE:
            await emit_debug_event(
                run_id,
                "parallel_fan_in",
                {"node": node_name, "from": list(_PARALLEL_NODES)},
            )
            await emit_debug_event(
                run_id,
                "node_started",
                {"node": node_name, "status": "running"},
            )
            await push_user_event(
                run_id,
                "agents_parallel_merged",
                {
                    "agents": list(_PARALLEL_NODES),
                    "summary": "证据检索完成，规则校验完成",
                },
            )

        elif node_name == "reflection":
            iterations = state.get("reflection_iterations", 0)
            await emit_debug_event(
                run_id,
                "node_started",
                {"node": node_name, "status": "running", "iteration": iterations},
            )

        else:
            await emit_debug_event(
                run_id,
                "node_started",
                {"node": node_name, "status": "running"},
            )

        result = await fn(state)

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        extra: dict = {"node": node_name, "latency_ms": latency_ms, "status": "completed"}

        # 附加 reflection 结果细节
        if node_name == "reflection" and isinstance(result, dict):
            passed = result.get("compliance_passed", True)
            iteration = result.get("reflection_iterations", 0)
            extra["compliance_passed"] = passed
            extra["reflection_iterations"] = iteration
            await emit_debug_event(
                run_id,
                "reflection_iteration",
                {
                    "iteration": iteration,
                    "passed": passed,
                    "issues": result.get("compliance_issues", []),
                },
            )
            # 用户侧只传类别化的 issue_category，不传原始违规文本（docs/backend-prd-v2.md
            # §5.7 隐私约束）。当前 Reflection 只做合规/过度承诺检测，未通过统一归类为
            # over_promise；evidence_gap 留给未来 check_evidence_coverage 落地后再启用。
            await push_user_event(
                run_id,
                "self_check_round",
                {
                    "iteration": iteration,
                    "max_iterations": _MAX_REFLECTION_ITERATIONS,
                    "issue_category": "none" if passed else "over_promise",
                    "status": "passed" if passed else "revising",
                },
            )

        await emit_debug_event(run_id, "node_completed", extra)
        return result

    _wrapped.__name__ = fn.__name__
    return _wrapped


def _route_after_data_resolver(state: VolunteerPlanState) -> list[str]:
    """
    PROFILE_CHECK：档案完整则并行进入检索+规则校验，否则转 profile_agent 追问并结束 run。
    返回列表以支持"完整"分支同时触发两个并行节点（LangGraph 支持条件路由返回多个目标）。
    """
    if state.get("profile_complete", False):
        return ["retrieval_agent", "policy_rule_agent"]
    return ["profile_agent"]


def _route_after_reflection(state: VolunteerPlanState) -> str:
    """
    Reflection Agent 完成后的条件路由。

    返回值二选一："end" | "report"
    """
    compliance_passed = state.get("compliance_passed", False)
    iterations = state.get("reflection_iterations", 0)

    if compliance_passed:
        return "end"

    if iterations >= _MAX_REFLECTION_ITERATIONS:
        raise RuntimeError("报告在最大重试次数内未通过合规审查")

    return "report"


def create_graph(checkpointer=None):
    """
    构建并编译 LangGraph 状态机。

    `checkpointer` 在每个 superstep 之后持久化状态，这样崩溃/被杀掉的 worker
    可以从某个 thread_id 最后完成的节点恢复，而不必重跑整张图
    （见 docs/memory-architecture.md §六 P1）。
    默认为 None，供只检查拓扑结构、不需要持久化的结构测试使用。
    """
    graph = StateGraph(VolunteerPlanState)

    # ── 节点（全部包装了 debug 事件发射逻辑） ──────────────────────
    graph.add_node("data_resolver", _wrap_with_debug("data_resolver", data_resolver))
    graph.add_node("profile_agent", _wrap_with_debug("profile_agent", profile_agent))
    graph.add_node("retrieval_agent", _wrap_with_debug("retrieval_agent", retrieval_agent))
    graph.add_node("policy_rule_agent", _wrap_with_debug("policy_rule_agent", policy_rule_agent))
    graph.add_node("recommendation", _wrap_with_debug("recommendation", recommendation_agent))
    graph.add_node("risk", _wrap_with_debug("risk", risk_node))
    graph.add_node("report", _wrap_with_debug("report", report_agent))
    graph.add_node("reflection", _wrap_with_debug("reflection", reflection_agent))

    # ── 边 ──────────────────────────────────────────────────────────────
    graph.set_entry_point("data_resolver")

    # PROFILE_CHECK：档案完整 → fan-out 到两个并行 agent；不完整 → profile_agent
    graph.add_conditional_edges(
        "data_resolver",
        _route_after_data_resolver,
        {
            "retrieval_agent": "retrieval_agent",
            "policy_rule_agent": "policy_rule_agent",
            "profile_agent": "profile_agent",
        },
    )
    graph.add_edge("profile_agent", END)

    # fan-in：两个并行 agent → recommendation（LangGraph 会等待两者都完成）
    graph.add_edge("retrieval_agent", "recommendation")
    graph.add_edge("policy_rule_agent", "recommendation")

    graph.add_edge("recommendation", "risk")
    graph.add_edge("risk", "report")
    graph.add_edge("report", "reflection")

    # reflection 之后的条件路由（重试循环或终止）
    graph.add_conditional_edges(
        "reflection",
        _route_after_reflection,
        {
            "end": END,
            "report": "report",
        },
    )

    return graph.compile(checkpointer=checkpointer)


def create_refine_graph(checkpointer=None):
    """
    局部重新生成子图 (docs/backend-prd-v2.md §5.9)：只重跑
    recommendation → risk → report → reflection，复用调用方在初始 state 里
    传入的 evidence_list（来自被 refine 报告的 evidence_json），不重新走
    data_resolver/retrieval_agent/policy_rule_agent。节点函数与主图完全一致，
    只是入口和跳过的前置节点不同。
    """
    graph = StateGraph(VolunteerPlanState)

    graph.add_node("recommendation", _wrap_with_debug("recommendation", recommendation_agent))
    graph.add_node("risk", _wrap_with_debug("risk", risk_node))
    graph.add_node("report", _wrap_with_debug("report", report_agent))
    graph.add_node("reflection", _wrap_with_debug("reflection", reflection_agent))

    graph.set_entry_point("recommendation")
    graph.add_edge("recommendation", "risk")
    graph.add_edge("risk", "report")
    graph.add_edge("report", "reflection")

    graph.add_conditional_edges(
        "reflection",
        _route_after_reflection,
        {
            "end": END,
            "report": "report",
        },
    )

    return graph.compile(checkpointer=checkpointer)


# 模块级别、不带 checkpointer 的编译图 —— 仅供结构测试
# （test_graph_structure.py）检查拓扑而不实际执行节点使用。Worker 会在启动时
# 自行构建带 checkpointer 的实例（见 worker.py on_startup），因为
# AsyncPostgresSaver 需要异步连接池，无法在 import 时就建好。
agent_graph = create_graph()
refine_graph = create_refine_graph()
