"""
search_school_documents 命中真实检索结果时，IntakeAgent 必须发起第二次流式请求
让模型读完片段再组织语言（retrieve -> augment -> generate 的最后一步），不能像
SQL 工具那样直接把检索片段模板化原样返回给用户——2026-08-24 实测验证时发现直接
模板化会把跑题/无关片段一起原样甩给用户，见 backend/docs/02_agent_design.md
§10.2 "为什么这个工具命中结果时要发第二次流式请求"。

这里用 monkeypatch 模拟两次 _stream_chat 调用（第一次 use_tools=True 触发
tool_calls，第二次 use_tools=False 是模型基于检索片段生成的最终回答），并 mock
掉 _execute_tool_call 避免依赖真实数据库/向量检索，只验证 stream_intake_response
的编排逻辑：确实发起了第二次生成，且最终回复是"模型生成的文本"而不是"原始 chunk
摘录模板"。
"""
from __future__ import annotations

import json

import pytest

from app.agent import intake_agent


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


_FAKE_CHUNKS = [
    {
        "title": "东华大学2026年本科招生章程",
        "excerpt": "（1）文科类学费标准为6500元/生*学年，理工类学费标准为7000元/生*学年。",
        "source_url": "https://zs.dhu.edu.cn/2026/0528/c9563a376561/page.htm",
        "section_title": None,
    }
]

_SYNTHESIZED_ANSWER = "东华大学文理类学费6500-7700元/学年，来源见章程。"


async def _fake_stream(client, messages, *, use_tools, conversation_id=None):
    if use_tools:
        yield {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "search_school_documents", "arguments": ""},
                    }]
                },
                "finish_reason": None,
            }]
        }
        yield {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {
                            "arguments": json.dumps(
                                {"university_name": "东华大学", "query": "学费标准"}, ensure_ascii=False
                            )
                        },
                    }]
                },
                "finish_reason": "tool_calls",
            }]
        }
    else:
        # 第二次请求（合成回答）不能再带 tools——否则可能递归触发新一轮工具调用
        yield {"choices": [{"delta": {"content": _SYNTHESIZED_ANSWER}, "finish_reason": "stop"}]}


async def _fake_execute_tool_call(name: str, arguments_json: str) -> dict:
    assert name == "search_school_documents"
    return {
        "status": "SUCCESS",
        "text": "东华大学 检索到 1 条相关文档片段",
        "data": {"university_name": "东华大学", "chunks": _FAKE_CHUNKS},
    }


@pytest.mark.asyncio
async def test_search_school_documents_hit_triggers_second_generation_not_raw_dump(monkeypatch):
    monkeypatch.setattr(intake_agent.httpx, "AsyncClient", _DummyAsyncClient)
    monkeypatch.setattr(intake_agent, "_stream_chat", _fake_stream)
    monkeypatch.setattr(intake_agent, "_execute_tool_call", _fake_execute_tool_call)

    events = [
        event
        async for event in intake_agent.stream_intake_response(
            history=[], user_message="东华大学学费标准是多少？"
        )
    ]

    full_text = "".join(e["content"] for e in events if e["type"] == "token")
    done_event = next(e for e in events if e["type"] == "done")

    assert _SYNTHESIZED_ANSWER in full_text
    assert done_event["full_response"] == full_text
    # 原始 chunk 摘录文本不应该原样出现——如果出现说明退化回了"直接模板化"的旧行为
    assert _FAKE_CHUNKS[0]["excerpt"] not in full_text


@pytest.mark.asyncio
async def test_search_school_documents_partial_result_still_uses_deterministic_text(monkeypatch):
    """检索不到内容时（PARTIAL/ERROR）没有必要为了一句"暂无该数据"发起第二次生成，
    继续用工具自带的确定性文案，跟 SQL 工具找不到记录时的行为保持一致。"""
    monkeypatch.setattr(intake_agent.httpx, "AsyncClient", _DummyAsyncClient)
    monkeypatch.setattr(intake_agent, "_stream_chat", _fake_stream)

    async def _fake_no_hit(name: str, arguments_json: str) -> dict:
        return {
            "status": "PARTIAL",
            "text": "东华大学 暂无与「学费标准」相关的文档记录",
            "data": {"university_name": "东华大学", "chunks": []},
        }

    monkeypatch.setattr(intake_agent, "_execute_tool_call", _fake_no_hit)

    events = [
        event
        async for event in intake_agent.stream_intake_response(
            history=[], user_message="东华大学学费标准是多少？"
        )
    ]

    full_text = "".join(e["content"] for e in events if e["type"] == "token")
    assert full_text == "东华大学 暂无与「学费标准」相关的文档记录"
