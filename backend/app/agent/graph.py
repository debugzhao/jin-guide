"""
LangGraph state machine for 问津 Agent (Day 8).

M3 graph topology (adds Reflection loop + Human Review interrupt):

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
       /    |    \\
    END  report  human_review → END

Conditional routing from reflection:
  compliance_passed AND NOT needs_human_review → END
  NOT compliance_passed AND iterations < 3     → report (retry)
  otherwise                                    → human_review

interrupt() in human_review_node requires a checkpointer.
MemorySaver is used for MVP (works within a single worker process).
For production, replace with AsyncPostgresSaver (langgraph-checkpoint-postgres).
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agent.state import VolunteerPlanState
from app.agent.nodes.data_resolver import data_resolver
from app.agent.nodes.retrieval_agent import retrieval_agent
from app.agent.nodes.policy_rule_agent import policy_rule_agent
from app.agent.nodes.recommendation_agent import recommendation_agent
from app.agent.nodes.risk import risk_node
from app.agent.nodes.report_agent import report_agent
from app.agent.nodes.reflection_agent import reflection_agent
from app.agent.nodes.human_review import human_review_node

_MAX_REFLECTION_ITERATIONS = 3


def _route_after_reflection(state: VolunteerPlanState) -> str:
    """
    Conditional routing after Reflection Agent completes.

    Returns one of: "end" | "report" | "human_review"
    """
    compliance_passed = state.get("compliance_passed", True)
    needs_human_review = state.get("needs_human_review", False)
    iterations = state.get("reflection_iterations", 0)

    if compliance_passed and not needs_human_review:
        return "end"

    if not compliance_passed and iterations < _MAX_REFLECTION_ITERATIONS:
        return "report"  # retry: report agent will regenerate with compliance_issues context

    # Max iterations exceeded or risk engine flagged human review
    return "human_review"


def create_graph(checkpointer=None):
    """
    Build and compile the LangGraph state machine.

    Args:
        checkpointer: LangGraph checkpointer instance. Required for interrupt().
            Defaults to a module-level MemorySaver if not provided.
    """
    graph = StateGraph(VolunteerPlanState)

    # ── Nodes ──────────────────────────────────────────────────────────────
    graph.add_node("data_resolver", data_resolver)
    graph.add_node("retrieval_agent", retrieval_agent)
    graph.add_node("policy_rule_agent", policy_rule_agent)
    graph.add_node("recommendation", recommendation_agent)
    graph.add_node("risk", risk_node)
    graph.add_node("report", report_agent)
    graph.add_node("reflection", reflection_agent)
    graph.add_node("human_review", human_review_node)

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
            "human_review": "human_review",
        },
    )

    graph.add_edge("human_review", END)

    return graph.compile(checkpointer=checkpointer)


# Module-level checkpointer (MemorySaver for MVP; survives within a worker process)
_checkpointer = MemorySaver()

# Module-level compiled graph instance — workers import this directly
agent_graph = create_graph(checkpointer=_checkpointer)
