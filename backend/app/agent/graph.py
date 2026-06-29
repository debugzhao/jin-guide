from langgraph.graph import END, StateGraph

from app.agent.state import VolunteerPlanState
from app.agent.nodes.mock_nodes import (
    mock_data_resolver,
    mock_report,
    mock_recommendation,
    mock_retrieval_and_rules,
    mock_risk,
)


def create_graph():
    """
    Build the LangGraph state machine for volunteer plan generation.

    M1: Linear sequential graph with mock nodes.
    M2: Replace mock nodes with real agent implementations.
    M3: Add parallel branches (Retrieval + PolicyRule via Send API),
        Reflection loop, and human_review_node with interrupt().

    See PRD Section 10.3 for the full production workflow diagram.
    """
    graph = StateGraph(VolunteerPlanState)

    graph.add_node("data_resolver", mock_data_resolver)
    graph.add_node("retrieval_and_rules", mock_retrieval_and_rules)
    graph.add_node("recommendation", mock_recommendation)
    graph.add_node("risk", mock_risk)
    graph.add_node("report", mock_report)

    graph.set_entry_point("data_resolver")
    graph.add_edge("data_resolver", "retrieval_and_rules")
    graph.add_edge("retrieval_and_rules", "recommendation")
    graph.add_edge("recommendation", "risk")
    graph.add_edge("risk", "report")
    graph.add_edge("report", END)

    return graph.compile()


# Module-level compiled graph instance
# Workers import this directly to avoid recompiling per invocation
agent_graph = create_graph()
