"""
Unit tests for human_review.py — Day 8 HITL interrupt node.

Tests cover:
  - render_review_draft: LLM success path and fallback structure
  - human_review_node: DB record creation, SSE push, interrupt call
  - Graph topology: reflection and human_review nodes in graph
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_state(
    risk_items=None,
    compliance_issues=None,
    review_reasons=None,
    needs_human_review=True,
    iterations=3,
) -> dict:
    return {
        "run_id": "test-run-hitl",
        "thread_id": "thread-test",
        "report_id": "report-test-123",
        "profile": {"rank": 32680, "province": "河南", "score": 612},
        "risk_items": risk_items or [{"risk_type": "insufficient_safety", "severity": "high", "message": "保底不足", "targets": []}],
        "compliance_issues": compliance_issues or ["录取概率极高"],
        "review_reasons": review_reasons or ["高风险"],
        "needs_human_review": needs_human_review,
        "reflection_iterations": iterations,
        "data_warnings": ["历年数据仅2年"],
    }


# ── render_review_draft ────────────────────────────────────────────────────────

class TestRenderReviewDraft:
    @pytest.mark.asyncio
    async def test_llm_success_path(self):
        """When LLM returns valid JSON, checklist_json uses LLM output."""
        from app.agent.nodes.human_review import _render_review_draft

        llm_response_json = (
            '{"summary": "学生位次32680，保底不足，触发复核", '
            '"reviewer_checklist": [{"id": "c1", "item": "保底数量", "required": true}]}'
        )

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": llm_response_json}}]
        }

        with patch("app.agent.nodes.human_review.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_resp)

            draft = await _render_review_draft(_make_state())

        assert "summary" in draft
        assert "reviewer_checklist" in draft
        assert "trigger_reasons" in draft
        assert "risk_items" in draft

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self):
        """When LLM call fails, fallback generates rule-based draft."""
        from app.agent.nodes.human_review import _render_review_draft

        with patch("app.agent.nodes.human_review.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.side_effect = Exception("LLM error")

            draft = await _render_review_draft(_make_state())

        assert "summary" in draft
        assert "reviewer_checklist" in draft
        assert len(draft["reviewer_checklist"]) >= 2
        # Fallback checklist has at least one required item
        required = [c for c in draft["reviewer_checklist"] if c.get("required")]
        assert len(required) >= 1

    @pytest.mark.asyncio
    async def test_trigger_reasons_reflect_compliance_issues(self):
        """When compliance_issues present, trigger_reasons includes compliance_failed."""
        from app.agent.nodes.human_review import _render_review_draft

        with patch("app.agent.nodes.human_review.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.side_effect = Exception("LLM error")
            draft = await _render_review_draft(
                _make_state(compliance_issues=["保证录取"], iterations=3)
            )

        assert "compliance_failed" in draft["trigger_reasons"]

    @pytest.mark.asyncio
    async def test_trigger_reasons_reflect_max_iterations(self):
        """When iterations >= 3, trigger_reasons includes reflection_max_iterations."""
        from app.agent.nodes.human_review import _render_review_draft

        with patch("app.agent.nodes.human_review.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.side_effect = Exception("LLM error")
            draft = await _render_review_draft(
                _make_state(compliance_issues=[], iterations=3)
            )

        assert "reflection_max_iterations" in draft["trigger_reasons"]

    @pytest.mark.asyncio
    async def test_draft_includes_risk_items(self):
        """Risk items are forwarded into the draft for reviewer."""
        from app.agent.nodes.human_review import _render_review_draft

        with patch("app.agent.nodes.human_review.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.side_effect = Exception("LLM error")
            draft = await _render_review_draft(_make_state())

        assert len(draft["risk_items"]) >= 1
        assert draft["risk_items"][0]["risk_type"] == "insufficient_safety"

    @pytest.mark.asyncio
    async def test_draft_includes_data_warnings(self):
        """data_warnings forwarded into draft."""
        from app.agent.nodes.human_review import _render_review_draft

        with patch("app.agent.nodes.human_review.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.side_effect = Exception("LLM error")
            draft = await _render_review_draft(_make_state())

        assert "历年数据仅2年" in draft["data_warnings"]


# ── human_review_node ─────────────────────────────────────────────────────────

class TestHumanReviewNode:
    @pytest.mark.asyncio
    async def test_node_creates_db_record_and_pushes_sse(self):
        """human_review_node creates HumanReview record and pushes human_interrupt SSE."""
        from app.agent.nodes.human_review import human_review_node

        # Mock all external calls
        mock_draft = {
            "summary": "测试复核",
            "trigger_reasons": ["high_risk"],
            "risk_items": [],
            "compliance_issues": [],
            "data_warnings": [],
            "reviewer_checklist": [{"id": "c1", "item": "测试项", "required": True}],
        }

        sse_calls = []
        db_calls = []

        async def mock_render_draft(state):
            return mock_draft

        async def mock_create_record(state, checklist, review_id):
            db_calls.append(review_id)

        async def mock_push_sse(run_id, event, data):
            sse_calls.append({"run_id": run_id, "event": event, "data": data})

        with patch("app.agent.nodes.human_review._render_review_draft", side_effect=mock_render_draft), \
             patch("app.agent.nodes.human_review._create_review_record", side_effect=mock_create_record), \
             patch("app.agent.nodes.human_review._push_sse", side_effect=mock_push_sse):

            # Mock interrupt() to return a resume payload instead of pausing
            resume_payload = {
                "review_conclusion": "approved",
                "reviewer_notes": "合规，通过",
            }
            with patch("app.agent.nodes.human_review.interrupt", return_value=resume_payload):
                # Mock DB update after resume
                mock_db = MagicMock()
                mock_db.__aenter__ = AsyncMock(return_value=mock_db)
                mock_db.__aexit__ = AsyncMock(return_value=None)
                mock_db.execute = AsyncMock(
                    return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
                )
                with patch("app.agent.nodes.human_review.async_session_maker", return_value=mock_db):
                    result = await human_review_node(_make_state())

        assert len(db_calls) == 1  # DB record created
        assert len(sse_calls) == 1  # SSE pushed
        assert sse_calls[0]["event"] == "human_interrupt"
        assert "review_task_id" in result

    @pytest.mark.asyncio
    async def test_node_sse_event_contains_sla_hours(self):
        """SSE human_interrupt event contains sla_hours field."""
        from app.agent.nodes.human_review import human_review_node

        sse_calls = []

        async def mock_render_draft(state):
            return {"summary": "x", "trigger_reasons": [], "risk_items": [], "compliance_issues": [], "data_warnings": [], "reviewer_checklist": []}

        async def mock_create_record(state, checklist, review_id):
            pass

        async def mock_push_sse(run_id, event, data):
            sse_calls.append(data)

        with patch("app.agent.nodes.human_review._render_review_draft", side_effect=mock_render_draft), \
             patch("app.agent.nodes.human_review._create_review_record", side_effect=mock_create_record), \
             patch("app.agent.nodes.human_review._push_sse", side_effect=mock_push_sse):

            with patch("app.agent.nodes.human_review.interrupt", return_value={}):
                mock_db = MagicMock()
                mock_db.__aenter__ = AsyncMock(return_value=mock_db)
                mock_db.__aexit__ = AsyncMock(return_value=None)
                mock_db.execute = AsyncMock(
                    return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
                )
                with patch("app.agent.nodes.human_review.async_session_maker", return_value=mock_db):
                    await human_review_node(_make_state())

        assert sse_calls[0]["sla_hours"] == 4


# ── Graph topology ─────────────────────────────────────────────────────────────

class TestGraphTopologyDay8:
    def test_reflection_node_in_graph(self):
        from app.agent.graph import agent_graph
        assert "reflection" in set(agent_graph.nodes)

    def test_human_review_node_in_graph(self):
        from app.agent.graph import agent_graph
        assert "human_review" in set(agent_graph.nodes)

    def test_graph_has_eight_nodes(self):
        from app.agent.graph import agent_graph
        nodes = set(agent_graph.nodes)
        expected = {
            "data_resolver", "retrieval_agent", "policy_rule_agent",
            "recommendation", "risk", "report", "reflection", "human_review"
        }
        assert expected.issubset(nodes), f"Missing nodes: {expected - nodes}"

    def test_graph_compiles_with_checkpointer(self):
        from app.agent.graph import create_graph
        from langgraph.checkpoint.memory import MemorySaver
        g = create_graph(checkpointer=MemorySaver())
        assert g is not None
