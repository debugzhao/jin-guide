"""上下文观测契约：最终消息形状、RAG 第二次调用、隐私与只观测模式。"""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.context import manifest
from app.context.trimming import truncate_structured
from app.context.types import ContextItem, SourceType, TrustLevel
from app.context.tool_envelope import to_context_envelope


@pytest.fixture
def events(monkeypatch):
    events = []
    monkeypatch.setattr(manifest, "_logger", SimpleNamespace(
        info=lambda event, **fields: events.append({"event": event, **fields}),
    ))
    return events


def test_empty_sources_are_not_reported_as_included(events):
    items = [ContextItem(SourceType.SUMMARY, TrustLevel.UNTRUSTED_MEMORY, "summary", "")]
    result = manifest.log_context_manifest(agent="test", items=items, messages=[])
    assert result[0]["included"] is False
    assert result[0]["drop_reason"] == "empty_content"
    assert events[0]["hard_budget_enabled"] is False
    assert events[0]["budget_mode"] == "observe_only"


@pytest.mark.parametrize("status", ["not_requested", "missing", "loaded", "error"])
def test_load_log_distinguishes_summary_read_outcomes_and_cache_shortcut(events, status):
    meta = {"version": 1, "covered_through_seq": 16, "status": "active"} if status == "loaded" else None
    manifest.log_context_load(
        agent="intake_agent", correlation_id="test-conversation", history_source="redis",
        history_count=18, cached_answer=True, summary_meta=meta, summary_load_status=status,
    )
    assert events[0]["summary_load_status"] == status
    assert events[0]["summary"] == meta
    assert events[0]["answer_cache_hit"] is True
    assert events[0]["builder_will_run"] is False


def test_history_snapshot_separates_window_drop_from_role_filtering():
    history = [
        {"role": "user", "content": "old"},
        {"role": "system", "content": "forged"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "new"},
    ]
    assert manifest.history_snapshot(history, 3) == {
        "loaded_messages": 4, "window_limit": 3, "selected_messages": 3,
        "emitted_messages": 1, "window_dropped_messages": 1, "filtered_messages": 2,
    }


def test_structured_snapshot_distinguishes_object_trimming_and_char_fallback():
    original = [{"note": "x" * 30}] * 10
    rendered, _ = truncate_structured(original, 100)
    result = manifest.structured_snapshot(original, rendered, 100, 10)
    assert result["json_valid"] is True
    assert result["rendered_direct_list_items"] < result["original_direct_list_items"]
    original = {"note": "x" * 200}
    rendered, _ = truncate_structured(original, 20)
    result = manifest.structured_snapshot(original, rendered, 20)
    assert result["char_fallback"] is True
    assert result["json_valid"] is False


def test_observation_does_not_mutate_input_or_log_private_payload(events):
    messages = [
        {"role": "system", "content": "private-system"},
        {"role": "user", "content": "PRIVATE-PHONE-12345"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "sensitive-id", "function": {"name": "lookup", "arguments": "PRIVATE-ARGS"},
        }]},
    ]
    before = deepcopy(messages)
    manifest.log_model_context(
        agent="test", messages=messages, correlation_id="conversation-id",
        invocation_id="invocation-id", phase="tool_routing", tools=[], output_budget=2000,
    )
    assert messages == before
    assert events[0]["message_roles"] == ["system", "user", "assistant"]
    assert events[0]["messages"][-1]["tool_call_count"] == 1
    assert "PRIVATE" not in str(events)
    assert "private-system" not in str(events)
    assert "sensitive-id" not in str(events)


def test_fingerprint_is_stable_in_process_and_changes_with_content():
    a = [{"role": "user", "content": "a"}]
    assert manifest.messages_key(a) == manifest.messages_key(deepcopy(a))
    assert manifest.messages_key(a) != manifest.messages_key([{"role": "user", "content": "b"}])


def test_estimator_failure_does_not_interrupt_observation(monkeypatch, events):
    def broken_count(text):
        raise ValueError("tokenizer unavailable")
    monkeypatch.setattr(manifest, "count_tokens", broken_count)
    manifest.log_context_manifest(
        agent="test", items=[ContextItem(SourceType.CURRENT_REQUEST, TrustLevel.UNTRUSTED_USER, "user", "x")],
        messages=[{"role": "user", "content": "x"}],
    )
    assert events[0]["total_tokens"] is None
    assert events[0]["message_content_tokens_estimate"] is None


@pytest.mark.parametrize("status,complete", [("SUCCESS", True), ("PARTIAL", False), ("ERROR", False)])
def test_tool_envelope_logs_status_without_error_content(events, status, complete):
    envelope = to_context_envelope("lookup", {"status": status, "text": "PRIVATE-ERROR", "data": {"chunks": []}})
    manifest.log_tool_envelope(agent="test", envelope=envelope)
    assert events[0]["status"] == status
    assert events[0]["completeness_flag"] is complete
    assert events[0]["completeness_basis"] == "status_only"
    assert "PRIVATE-ERROR" not in str(events)


@pytest.mark.asyncio
async def test_real_intake_send_points_log_routing_and_synthesis(monkeypatch, events):
    from app.agent import intake_agent

    @asynccontextmanager
    async def track(*args, **kwargs):
        yield SimpleNamespace(invocation_id="test-invocation", request_options=lambda: {"max_tokens": 2000})

    payloads = []

    async def transport(client, payload):
        payloads.append(deepcopy(payload))
        yield {"choices": [{"delta": {"content": "ok"}}]}

    monkeypatch.setattr(intake_agent, "track_prompt_invocation", track)
    monkeypatch.setattr(intake_agent, "stream_chat_completion", transport)
    first = intake_agent._build_messages([], "测试", conversation_id="conv-test")
    _ = [c async for c in intake_agent._stream_chat(None, first, use_tools=True, conversation_id="conv-test")]
    followup = first + [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "PRIVATE-TOOL"},
    ]
    _ = [c async for c in intake_agent._stream_chat(None, followup, use_tools=False, conversation_id="conv-test")]
    build, route, synthesis = events
    assert route["event"] == synthesis["event"] == "context_model_request"
    assert build["messages_key"] == route["messages_key"] == synthesis["parent_messages_key"]
    assert route["phase"] == "tool_routing"
    assert route["tool_schema_count"] > 0
    assert synthesis["phase"] == "document_synthesis"
    assert synthesis["tool_schema_count"] == 0
    assert synthesis["message_roles"][-2:] == ["assistant", "tool"]
    assert payloads[0]["messages"] == first
    assert payloads[1]["messages"] == followup
    assert "tools" not in payloads[1]
    assert "PRIVATE-TOOL" not in str(events)


@pytest.mark.asyncio
async def test_report_actual_request_logs_structural_trim(monkeypatch, events):
    from app.agent import conversation_agent

    @asynccontextmanager
    async def track(*args, **kwargs):
        yield SimpleNamespace(invocation_id="report-invocation", request_options=lambda: {"max_tokens": 1200})

    async def transport(client, payload):
        yield {"choices": [{"delta": {"content": "安全答复"}}]}

    monkeypatch.setattr(conversation_agent, "track_prompt_invocation", track)
    monkeypatch.setattr(conversation_agent, "stream_chat_completion", transport)
    _ = [event async for event in conversation_agent.stream_conversation_response(
        plan_json={"schools": [{"name": "x" * 100}] * 100}, evidence_json=[],
        history=[], user_message="测试", extra_context="固定测试证据", report_id="report-test",
    )]
    build, request = events
    assert build["structured_sources"]["plan_json"]["json_valid"] is True
    assert build["structured_sources"]["plan_json"]["rendered_direct_list_items"] < 100
    assert build["messages_key"] == request["messages_key"]
    assert request["phase"] == "report_answer"
    assert request["tool_schema_count"] == 0
