from langgraph.graph import END, StateGraph

from app.agent.state import VolunteerPlanState
from app.agent.nodes.data_resolver import data_resolver
from app.agent.nodes.retrieval_agent import retrieval_agent
from app.agent.nodes.policy_rule_agent import policy_rule_agent
from app.agent.nodes.recommendation_agent import recommendation_agent
from app.agent.nodes.risk import risk_node
from app.agent.nodes.report_agent import report_agent


def create_graph():
    """
    Build the LangGraph state machine for volunteer plan generation.

    M2 graph topology (parallel fan-out at data_resolver):

        data_resolver
           /        \\
    retrieval_agent  policy_rule_agent   (parallel)
           \\        /
        recommendation
              |
             risk
              |
            report
              |
             END

    Parallel merge is handled automatically by LangGraph when both
    retrieval_agent and policy_rule_agent edge into recommendation:
    LangGraph waits for all incoming nodes before executing the target.
    Annotated[list, operator.add] reducers in state prevent overwrite.
    """
    graph = StateGraph(VolunteerPlanState)

    graph.add_node("data_resolver", data_resolver)
    graph.add_node("retrieval_agent", retrieval_agent)
    graph.add_node("policy_rule_agent", policy_rule_agent)
    graph.add_node("recommendation", recommendation_agent)
    graph.add_node("risk", risk_node)
    graph.add_node("report", report_agent)

    graph.set_entry_point("data_resolver")

    # Fan-out: data_resolver -> both parallel agents
    graph.add_edge("data_resolver", "retrieval_agent")
    graph.add_edge("data_resolver", "policy_rule_agent")

    # Fan-in: both parallel agents -> recommendation (LangGraph waits for both)
    graph.add_edge("retrieval_agent", "recommendation")
    graph.add_edge("policy_rule_agent", "recommendation")

    graph.add_edge("recommendation", "risk")
    graph.add_edge("risk", "report")
    graph.add_edge("report", END)

    return graph.compile()


# Module-level compiled graph instance — workers import this directly
agent_graph = create_graph()
