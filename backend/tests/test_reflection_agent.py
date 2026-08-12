"""
Unit tests for reflection_agent.py — Day 8 compliance self-check.

Tests cover:
  - Layer 1 (regex) pass/fail paths
  - Layer 2 (LLM judge) early exit on passed=true and "无需改进"
  - LLM judge failure fallback (treats as passed)
  - Iteration counter incremented correctly
  - All issues deduplicated
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_state(
    plan: dict | None = None,
    iterations: int = 0,
    needs_human_review: bool = False,
) -> dict:
    return {
        "run_id": "test-run",
        "report_draft": plan or {"plans": [{"candidates": [{"recommendation_reasons": ["稳定录取，综合实力强"]}]}]},
        "reflection_iterations": iterations,
        "needs_human_review": needs_human_review,
    }


CLEAN_PLAN = {
    "plans": [
        {
            "candidates": [
                {"university_name": "郑州大学", "recommendation_reasons": ["历史录取稳定", "省内211"]}
            ]
        }
    ]
}

DIRTY_PLAN = {
    "plans": [
        {
            "candidates": [
                {"university_name": "某大学", "recommendation_reasons": ["保证录取，百分百没问题"]}
            ]
        }
    ]
}


# ── Layer 1 (regex) ────────────────────────────────────────────────────────────

class TestReflectionLayer1:
    @pytest.mark.asyncio
    async def test_layer1_clean_plan_calls_llm_judge(self):
        """When regex passes, Layer 2 LLM judge should be called."""
        from app.agent.nodes.reflection_agent import reflection_agent

        llm_result = {"passed": True, "feedback": "无需改进", "issues": []}
        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(return_value=llm_result),
        ) as mock_judge:
            state = _make_state(CLEAN_PLAN)
            result = await reflection_agent(state)

        assert result["compliance_passed"] is True
        assert result["compliance_issues"] == []
        assert result["reflection_iterations"] == 1
        mock_judge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_layer1_dirty_plan_fails_immediately(self):
        """When regex detects forbidden words, return fail without calling LLM."""
        from app.agent.nodes.reflection_agent import reflection_agent

        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(),
        ) as mock_judge:
            state = _make_state(DIRTY_PLAN)
            result = await reflection_agent(state)

        assert result["compliance_passed"] is False
        assert "保证录取" in result["compliance_issues"]
        mock_judge.assert_not_awaited()  # Layer 1 fail → skip Layer 2

    @pytest.mark.asyncio
    async def test_iteration_counter_increments(self):
        """reflection_iterations starts at 0 and increments +1 per call."""
        from app.agent.nodes.reflection_agent import reflection_agent

        llm_result = {"passed": True, "feedback": "无需改进", "issues": []}
        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(return_value=llm_result),
        ):
            state = _make_state(CLEAN_PLAN, iterations=0)
            result = await reflection_agent(state)
        assert result["reflection_iterations"] == 1

    @pytest.mark.asyncio
    async def test_iteration_counter_continues_from_existing(self):
        """If iterations=2 before call, result should be 3."""
        from app.agent.nodes.reflection_agent import reflection_agent

        llm_result = {"passed": True, "feedback": "无需改进", "issues": []}
        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(return_value=llm_result),
        ):
            state = _make_state(CLEAN_PLAN, iterations=2)
            result = await reflection_agent(state)
        assert result["reflection_iterations"] == 3


# ── Layer 2 (LLM judge) ────────────────────────────────────────────────────────

class TestReflectionLayer2:
    @pytest.mark.asyncio
    async def test_early_exit_on_passed_true(self):
        """LLM returns passed=true → compliance_passed=True, issues empty."""
        from app.agent.nodes.reflection_agent import reflection_agent

        llm_result = {"passed": True, "feedback": "内容合规", "issues": []}
        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(return_value=llm_result),
        ):
            result = await reflection_agent(_make_state(CLEAN_PLAN))

        assert result["compliance_passed"] is True
        assert result["compliance_issues"] == []

    @pytest.mark.asyncio
    async def test_feedback_cannot_override_failed_structured_result(self):
        """自然语言写“无需改进”也不能覆盖结构化 passed=false。"""
        from app.agent.nodes.reflection_agent import reflection_agent

        llm_result = {"passed": False, "feedback": "无需改进，报告内容合规", "issues": []}
        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(return_value=llm_result),
        ):
            result = await reflection_agent(_make_state(CLEAN_PLAN))

        assert result["compliance_passed"] is False

    @pytest.mark.asyncio
    async def test_llm_judge_fail_returns_issues(self):
        """LLM returns passed=false with issues → compliance_passed=False."""
        from app.agent.nodes.reflection_agent import reflection_agent

        llm_result = {
            "passed": False,
            "feedback": "发现过度承诺表述",
            "issues": ["录取概率极高"],
        }
        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(return_value=llm_result),
        ):
            result = await reflection_agent(_make_state(CLEAN_PLAN))

        assert result["compliance_passed"] is False
        assert "录取概率极高" in result["compliance_issues"]

    @pytest.mark.asyncio
    async def test_llm_judge_exception_fails_closed(self):
        """审查服务异常时必须失败关闭，不能把“未审查”当作“已通过”。"""
        from app.agent.nodes.reflection_agent import _llm_judge

        with patch(
            "app.agent.nodes.reflection_agent.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__.side_effect = Exception("connection error")
            result = await _llm_judge(CLEAN_PLAN, [])

        assert result["passed"] is False
        assert result["feedback"] == "合规审查暂时不可用"
        assert result["issues"] == ["合规审查服务不可用"]

    @pytest.mark.asyncio
    async def test_issues_deduplicated(self):
        """Issues from regex and LLM judge are deduplicated in output."""
        from app.agent.nodes.reflection_agent import reflection_agent

        # Plan with no regex issues but LLM finds semantic problem
        llm_result = {
            "passed": False,
            "feedback": "语义过度承诺",
            "issues": ["录取概率极高", "录取概率极高"],  # duplicates
        }
        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(return_value=llm_result),
        ):
            result = await reflection_agent(_make_state(CLEAN_PLAN))

        # Duplicates removed
        assert result["compliance_issues"].count("录取概率极高") == 1


# ── Graph routing function ─────────────────────────────────────────────────────

class TestReflectionRouting:
    def _call_route(self, state: dict) -> str:
        from app.agent.graph import _route_after_reflection
        return _route_after_reflection(state)

    def test_pass_no_review_routes_to_end(self):
        state = {
            "compliance_passed": True,
            "reflection_iterations": 1,
        }
        assert self._call_route(state) == "end"

    def test_fail_iter1_routes_to_report_retry(self):
        state = {
            "compliance_passed": False,
            "reflection_iterations": 1,
        }
        assert self._call_route(state) == "report"

    def test_fail_iter2_routes_to_report_retry(self):
        state = {
            "compliance_passed": False,
            "reflection_iterations": 2,
        }
        assert self._call_route(state) == "report"

    def test_fail_iter3_stops_delivery(self):
        """达最大轮次仍未通过时终止任务，不能交付未通过审查的报告。"""
        state = {
            "compliance_passed": False,
            "reflection_iterations": 3,
        }
        with pytest.raises(RuntimeError, match="未通过合规审查"):
            self._call_route(state)

    def test_fail_iter4_stops_delivery(self):
        """超过最大轮次同样不能降级放行。"""
        state = {
            "compliance_passed": False,
            "reflection_iterations": 4,
        }
        with pytest.raises(RuntimeError, match="未通过合规审查"):
            self._call_route(state)

    def test_default_state_does_not_fail_open(self):
        """缺失审查状态不能默认视为通过。"""
        assert self._call_route({}) == "report"
