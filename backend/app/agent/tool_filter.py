"""
ToolFilter: per-agent tool visibility registry (PRD §10.8).

Prevents LLM from hallucinating cross-agent tool calls by limiting
which tools each agent can see in its prompt context.
"""
from __future__ import annotations

_TOOL_REGISTRY: dict[str, list[str]] = {
    "retrieval_agent": ["search_admission_sql", "vector_search", "rerank_evidence"],
    "policy_rule_agent": [
        "check_subject_req",
        "check_medical_restriction",
        "check_batch_eligibility",
        "check_budget",
    ],
    "report_agent": [],  # LLM generation only, no tool calls
}


class ToolFilter:
    def __init__(self, agent_name: str) -> None:
        self._allowed: set[str] = set(_TOOL_REGISTRY.get(agent_name, []))
        self._agent = agent_name

    def is_allowed(self, tool_name: str) -> bool:
        return tool_name in self._allowed

    def allowed_names(self) -> list[str]:
        return sorted(self._allowed)

    def filter(self, tools: list) -> list:
        """Return only tools that are allowed for this agent."""
        return [t for t in tools if getattr(t, "name", None) in self._allowed]

    def __repr__(self) -> str:
        return f"ToolFilter(agent={self._agent!r}, allowed={self.allowed_names()})"
