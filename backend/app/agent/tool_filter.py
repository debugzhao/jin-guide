"""
ToolFilter：按 Agent 划分的工具可见性注册表（PRD §10.8）。

通过限制每个 Agent 在其 Prompt 上下文中能看到哪些工具，
防止 LLM 臆造出跨 Agent 的工具调用。
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
    "profile_agent": [
        "check_subject_req",
        "check_batch_eligibility",
    ],
    "report_agent": [],  # 只做 LLM 生成，不涉及工具调用
    "risk_agent": [],  # 走确定性的 risk_engine 调用，不经过 LLM 工具调用
    "reflection_agent": [],  # 只做 LLM 判定，不涉及工具调用
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
        """只返回该 agent 被允许使用的工具。"""
        return [t for t in tools if getattr(t, "name", None) in self._allowed]

    def __repr__(self) -> str:
        return f"ToolFilter(agent={self._agent!r}, allowed={self.allowed_names()})"
