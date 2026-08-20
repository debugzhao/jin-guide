"""
reflection_agent.py 单元测试 —— Day 8 合规自检。

覆盖范围：
  - 第一层（正则）通过/不通过两条路径
  - 第二层（LLM judge）在 passed=true 且反馈为"无需改进"时提前退出
  - LLM judge 调用失败时的兜底行为（异常必须 fail closed，不能当作通过）
  - 迭代计数器正确累加
  - 所有 issue 去重
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
        """正则通过时，应继续调用第二层 LLM judge。"""
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
        """正则命中禁用词时应直接判定不通过，不需要再调用 LLM。"""
        from app.agent.nodes.reflection_agent import reflection_agent

        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(),
        ) as mock_judge:
            state = _make_state(DIRTY_PLAN)
            result = await reflection_agent(state)

        assert result["compliance_passed"] is False
        assert "保证录取" in result["compliance_issues"]
        mock_judge.assert_not_awaited()  # 第一层未通过 → 跳过第二层

    @pytest.mark.asyncio
    async def test_iteration_counter_increments(self):
        """reflection_iterations 初始为 0，每调用一次自增 1。"""
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
        """调用前 iterations=2，调用后结果应为 3。"""
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
        """LLM 返回 passed=true → compliance_passed=True，issues 为空。"""
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
        """LLM 返回 passed=false 且带 issues → compliance_passed=False。"""
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
            "app.agent.nodes.reflection_agent.call_chat_completion",
            new=AsyncMock(side_effect=Exception("connection error")),
        ):
            result = await _llm_judge(CLEAN_PLAN, [])

        assert result["passed"] is False
        assert result["feedback"] == "合规审查暂时不可用"
        assert result["issues"] == ["合规审查服务不可用"]

    @pytest.mark.asyncio
    async def test_issues_deduplicated(self):
        """正则和 LLM judge 各自发现的 issue 在输出中要合并去重。"""
        from app.agent.nodes.reflection_agent import reflection_agent

        # 方案本身没有触发正则规则，但 LLM 从语义层面发现了问题
        llm_result = {
            "passed": False,
            "feedback": "语义过度承诺",
            "issues": ["录取概率极高", "录取概率极高"],  # 重复项
        }
        with patch(
            "app.agent.nodes.reflection_agent._llm_judge",
            new=AsyncMock(return_value=llm_result),
        ):
            result = await reflection_agent(_make_state(CLEAN_PLAN))

        # 重复项已被去重
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
