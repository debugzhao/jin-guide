"""
Unit tests for tool_filter.py — per-agent tool visibility registry (PRD §10.8).
"""
import pytest
from app.agent.tool_filter import ToolFilter


class FakeTool:
    def __init__(self, name: str):
        self.name = name


# ── is_allowed ────────────────────────────────────────────────────────────────

class TestIsAllowed:
    def test_retrieval_agent_allowed_tools(self):
        f = ToolFilter("retrieval_agent")
        assert f.is_allowed("vector_search") is True
        assert f.is_allowed("search_admission_sql") is True
        assert f.is_allowed("rerank_evidence") is True

    def test_retrieval_agent_blocks_rule_tools(self):
        f = ToolFilter("retrieval_agent")
        assert f.is_allowed("check_subject_req") is False
        assert f.is_allowed("check_batch_eligibility") is False
        assert f.is_allowed("check_budget") is False

    def test_policy_rule_agent_allowed_tools(self):
        f = ToolFilter("policy_rule_agent")
        assert f.is_allowed("check_subject_req") is True
        assert f.is_allowed("check_medical_restriction") is True
        assert f.is_allowed("check_batch_eligibility") is True
        assert f.is_allowed("check_budget") is True

    def test_policy_rule_agent_blocks_retrieval_tools(self):
        f = ToolFilter("policy_rule_agent")
        assert f.is_allowed("vector_search") is False
        assert f.is_allowed("rerank_evidence") is False

    def test_report_agent_has_no_tools(self):
        f = ToolFilter("report_agent")
        assert f.is_allowed("vector_search") is False
        assert f.is_allowed("check_subject_req") is False
        assert f.allowed_names() == []

    def test_unknown_agent_blocks_everything(self):
        f = ToolFilter("nonexistent_agent")
        assert f.is_allowed("vector_search") is False
        assert f.is_allowed("check_budget") is False
        assert f.allowed_names() == []


# ── filter ────────────────────────────────────────────────────────────────────

class TestFilter:
    def test_filter_returns_only_allowed_tools(self):
        f = ToolFilter("retrieval_agent")
        tools = [
            FakeTool("vector_search"),
            FakeTool("check_subject_req"),  # belongs to policy_rule_agent
            FakeTool("rerank_evidence"),
            FakeTool("some_random_tool"),
        ]
        result = f.filter(tools)
        names = [t.name for t in result]
        assert "vector_search" in names
        assert "rerank_evidence" in names
        assert "check_subject_req" not in names
        assert "some_random_tool" not in names

    def test_filter_empty_list(self):
        f = ToolFilter("retrieval_agent")
        assert f.filter([]) == []

    def test_filter_report_agent_returns_empty(self):
        f = ToolFilter("report_agent")
        tools = [FakeTool("vector_search"), FakeTool("check_budget")]
        assert f.filter(tools) == []

    def test_filter_preserves_tool_objects(self):
        f = ToolFilter("policy_rule_agent")
        tool = FakeTool("check_budget")
        result = f.filter([tool])
        assert result[0] is tool


# ── allowed_names ─────────────────────────────────────────────────────────────

class TestAllowedNames:
    def test_retrieval_agent_has_three_tools(self):
        f = ToolFilter("retrieval_agent")
        names = f.allowed_names()
        assert len(names) == 3
        assert set(names) == {"vector_search", "search_admission_sql", "rerank_evidence"}

    def test_policy_rule_agent_has_four_tools(self):
        f = ToolFilter("policy_rule_agent")
        names = f.allowed_names()
        assert len(names) == 4

    def test_allowed_names_is_sorted(self):
        f = ToolFilter("retrieval_agent")
        names = f.allowed_names()
        assert names == sorted(names)

    def test_repr_contains_agent_name(self):
        f = ToolFilter("retrieval_agent")
        assert "retrieval_agent" in repr(f)
