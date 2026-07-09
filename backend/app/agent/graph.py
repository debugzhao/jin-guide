"""
LangGraph state machine for 问津 Agent.

Graph topology:

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

Conditional routing from data_resolver (PROFILE_CHECK):
  profile_complete       → [retrieval_agent, policy_rule_agent] (fan-out)
  NOT profile_complete   → profile_agent (追问，不生成报告，图在此结束)

Conditional routing from reflection:
  compliance_passed                    → END
  NOT compliance_passed AND iter < 3  → report (retry)
  max iterations exceeded              → END (best-effort)
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

_MAX_REFLECTION_ITERATIONS = 3

# Nodes that run in parallel after data_resolver
_PARALLEL_NODES = frozenset(["retrieval_agent", "policy_rule_agent"])
# Node that merges the parallel branches
_FAN_IN_NODE = "recommendation"


def _wrap_with_debug(node_name: str, fn: Callable) -> Callable:
    """
    Wrap a LangGraph node function to emit debug:node_started /
    debug:node_completed events around its execution.

    Also emits debug:parallel_fan_out when data_resolver completes and
    debug:parallel_fan_in when the merge node (recommendation) starts.
    """

    async def _wrapped(state: VolunteerPlanState) -> Any:
        run_id: str = state.get("run_id", "")
        t0 = time.perf_counter()

        # fan-out marker: fired once from data_resolver's completion
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

        # Attach reflection result details
        if node_name == "reflection" and isinstance(result, dict):
            extra["compliance_passed"] = result.get("compliance_passed", True)
            extra["reflection_iterations"] = result.get("reflection_iterations", 0)
            await emit_debug_event(
                run_id,
                "reflection_iteration",
                {
                    "iteration": result.get("reflection_iterations", 0),
                    "passed": result.get("compliance_passed", True),
                    "issues": result.get("compliance_issues", []),
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
    Conditional routing after Reflection Agent completes.

    Returns one of: "end" | "report"
    """
    compliance_passed = state.get("compliance_passed", True)
    iterations = state.get("reflection_iterations", 0)

    if compliance_passed or iterations >= _MAX_REFLECTION_ITERATIONS:
        return "end"

    return "report"


def create_graph():
    """Build and compile the LangGraph state machine."""
    graph = StateGraph(VolunteerPlanState)

    # ── Nodes (all wrapped with debug event emission) ──────────────────────
    graph.add_node("data_resolver", _wrap_with_debug("data_resolver", data_resolver))
    graph.add_node("profile_agent", _wrap_with_debug("profile_agent", profile_agent))
    graph.add_node("retrieval_agent", _wrap_with_debug("retrieval_agent", retrieval_agent))
    graph.add_node("policy_rule_agent", _wrap_with_debug("policy_rule_agent", policy_rule_agent))
    graph.add_node("recommendation", _wrap_with_debug("recommendation", recommendation_agent))
    graph.add_node("risk", _wrap_with_debug("risk", risk_node))
    graph.add_node("report", _wrap_with_debug("report", report_agent))
    graph.add_node("reflection", _wrap_with_debug("reflection", reflection_agent))

    # ── Edges ──────────────────────────────────────────────────────────────
    graph.set_entry_point("data_resolver")

    # PROFILE_CHECK: complete → fan-out to both parallel agents; incomplete → profile_agent
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

    # Fan-in: both parallel agents → recommendation (LangGraph waits for both)
    graph.add_edge("retrieval_agent", "recommendation")
    graph.add_edge("policy_rule_agent", "recommendation")

    graph.add_edge("recommendation", "risk")
    graph.add_edge("risk", "report")
    graph.add_edge("report", "reflection")

    # Conditional routing from reflection (loop or terminate)
    graph.add_conditional_edges(
        "reflection",
        _route_after_reflection,
        {
            "end": END,
            "report": "report",
        },
    )

    return graph.compile()


# Module-level compiled graph instance — workers import this directly
agent_graph = create_graph()
