"""
LangGraph state machine for 问津 Agent.

Graph topology:

    data_resolver
       /        \\
retrieval_agent  policy_rule_agent   (parallel fan-out)
       \\        /
    recommendation
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

Conditional routing from reflection:
  compliance_passed                    → END
  NOT compliance_passed AND iter < 3  → report (retry)
  max iterations exceeded              → END (best-effort)
"""
from langgraph.graph import END, StateGraph

from app.agent.state import VolunteerPlanState
from app.agent.nodes.data_resolver import data_resolver
from app.agent.nodes.retrieval_agent import retrieval_agent
from app.agent.nodes.policy_rule_agent import policy_rule_agent
from app.agent.nodes.recommendation_agent import recommendation_agent
from app.agent.nodes.risk import risk_node
from app.agent.nodes.report_agent import report_agent
from app.agent.nodes.reflection_agent import reflection_agent

_MAX_REFLECTION_ITERATIONS = 3


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

    # ── Nodes ──────────────────────────────────────────────────────────────
    graph.add_node("data_resolver", data_resolver)
    graph.add_node("retrieval_agent", retrieval_agent)
    graph.add_node("policy_rule_agent", policy_rule_agent)
    graph.add_node("recommendation", recommendation_agent)
    graph.add_node("risk", risk_node)
    graph.add_node("report", report_agent)
    graph.add_node("reflection", reflection_agent)

    # ── Edges ──────────────────────────────────────────────────────────────
    graph.set_entry_point("data_resolver")

    # Fan-out: data_resolver → both parallel agents
    graph.add_edge("data_resolver", "retrieval_agent")
    graph.add_edge("data_resolver", "policy_rule_agent")

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
