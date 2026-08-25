"""
ConversationAgent 的补充检索能力（`_retrieve_extra_context`）——之前 `extra_context`
参数虽然存在、`_build_messages` 也确实会把它包装成 untrusted-data 注入 messages，
但唯一调用方 `chat.py` 从未传过这个参数，检索永远不会真正发生（module docstring
里说的"vector_search 限定省份+年份检索"是从未落地的死代码）。2026-08-25 补上真正
实现：`stream_conversation_response` 在调用方没有显式传 `extra_context` 时自己
发起检索。这里验证：(1) 省份能从 evidence_json 正确推断；(2) 检索命中时结果真的
进了发给模型的 messages；(3) 检索失败/无结果时优雅降级，不影响主流程。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.conversation_agent import _infer_province, _retrieve_extra_context
from app.agent.tool_response import ToolResponse


class TestInferProvince:
    def test_returns_province_from_first_matching_evidence_item(self):
        evidence = [
            {"source_id": "src_001", "source_type": "admission_plan"},
            {"source_id": "src_002", "province": "河南"},
        ]
        assert _infer_province(evidence) == "河南"

    def test_returns_none_when_no_evidence_has_province(self):
        assert _infer_province([{"source_id": "src_001"}]) is None

    def test_returns_none_for_empty_or_missing_evidence(self):
        assert _infer_province([]) is None
        assert _infer_province(None) is None


class TestRetrieveExtraContext:
    @pytest.mark.asyncio
    async def test_no_province_short_circuits_without_touching_retrieval(self):
        with patch("app.engine.embedding.embed_text", new=AsyncMock()) as mock_embed:
            result = await _retrieve_extra_context("为什么推荐这所学校", [{"source_id": "src_001"}])

        assert result == ""
        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_hit_formats_chunks_with_source_citation(self):
        chunk = {
            "chunk_id": "c1",
            "document_id": "d1",
            "content": "计算机科学与技术专业选科要求为物理必选。",
            "metadata": {"source_url": "https://example.com/policy.htm"},
            "similarity": 0.9,
        }
        with (
            patch("app.engine.embedding.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.retrieval.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": [chunk]})),
            ),
            patch(
                "app.engine.retrieval.rerank_evidence",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": [chunk]})),
            ),
        ):
            result = await _retrieve_extra_context("选科要求是什么", [{"province": "河南"}])

        assert "计算机科学与技术专业选科要求为物理必选。" in result
        assert "https://example.com/policy.htm" in result

    @pytest.mark.asyncio
    async def test_no_vector_hits_degrades_to_empty_string(self):
        with (
            patch("app.engine.embedding.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.retrieval.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": []})),
            ),
        ):
            result = await _retrieve_extra_context("随便问问", [{"province": "河南"}])

        assert result == ""

    @pytest.mark.asyncio
    async def test_embedding_failure_degrades_to_empty_string_not_exception(self):
        """补充检索是可选项，不能因为它挂了就让整个问答请求跟着报错。"""
        with patch("app.engine.embedding.embed_text", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await _retrieve_extra_context("随便问问", [{"province": "河南"}])

        assert result == ""


class TestStreamConversationResponseAutoRetrieval:
    @pytest.mark.asyncio
    async def test_retrieved_context_reaches_the_model_when_caller_omits_extra_context(self, monkeypatch):
        from app.agent import conversation_agent

        captured_messages = {}

        async def _fake_retrieve(user_message, evidence_json):
            return "补充检索到的章程原文片段（来源：https://example.com）"

        async def _fake_stream_chat_completion(client, request_body):
            captured_messages["messages"] = request_body["messages"]
            yield {"choices": [{"delta": {"content": "好的，已参考补充资料回答。"}}]}

        monkeypatch.setattr(conversation_agent, "_retrieve_extra_context", _fake_retrieve)
        monkeypatch.setattr(conversation_agent, "stream_chat_completion", _fake_stream_chat_completion)
        monkeypatch.setattr(conversation_agent.httpx, "AsyncClient", _DummyAsyncClient)

        events = [
            event
            async for event in conversation_agent.stream_conversation_response(
                plan_json=None,
                evidence_json=[{"province": "河南"}],
                history=[],
                user_message="这个专业选科要求是什么",
            )
        ]

        all_message_text = " ".join(m.get("content", "") for m in captured_messages["messages"])
        assert "补充检索到的章程原文片段" in all_message_text
        assert 'trust="untrusted-data"' in all_message_text
        assert any(e["type"] == "done" for e in events)

    @pytest.mark.asyncio
    async def test_explicit_extra_context_is_not_overridden_by_auto_retrieval(self, monkeypatch):
        """兼容旧参数：调用方显式传了 extra_context 时不应该再触发自动检索。"""
        from app.agent import conversation_agent

        async def _should_not_be_called(user_message, evidence_json):
            raise AssertionError("不应该触发自动检索")

        async def _fake_stream_chat_completion(client, request_body):
            yield {"choices": [{"delta": {"content": "答复"}}]}

        monkeypatch.setattr(conversation_agent, "_retrieve_extra_context", _should_not_be_called)
        monkeypatch.setattr(conversation_agent, "stream_chat_completion", _fake_stream_chat_completion)
        monkeypatch.setattr(conversation_agent.httpx, "AsyncClient", _DummyAsyncClient)

        events = [
            event
            async for event in conversation_agent.stream_conversation_response(
                plan_json=None,
                evidence_json=[{"province": "河南"}],
                history=[],
                user_message="继续",
                extra_context="调用方显式传入的上下文",
            )
        ]

        assert any(e["type"] == "done" for e in events)
