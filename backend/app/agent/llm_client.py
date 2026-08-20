"""
Agent 节点/聊天 Agent 调用 LiteLLM 网关的统一入口。

各调用点原先各自手写 httpx 请求，完全脱离 LangSmith 的 tracing 上下文——
LangGraph 节点执行会自动生成父 run，但节点内部这次裸 httpx 调用不会作为子 run
挂上去，trace 里只看到节点耗时，看不到 prompt/completion/token。这里统一用
@traceable(run_type="llm") 包一层：函数执行时正处于调用方的活跃 trace 上下文内
（LangGraph 节点，或调用方自己开的 chain span），会被自动挂成子 run。

非流式（call_chat_completion）直接返回原始 completion JSON（含 usage 字段），
LangSmith 按 OpenAI 兼容格式自动识别并汇总 token。流式（stream_chat_completion）
则用 reduce_fn 把逐 chunk 的 delta 聚合成同样的 {choices, usage} 形状喂给
LangSmith——前提是请求体带了 stream_options.include_usage=true（见
app/prompts/models.py::PromptSpec.request_options），否则最后一个 chunk 不会
带 usage，聚合出来的 token 数会是空的。
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import httpx
from langsmith import traceable

from app.config import settings


@traceable(run_type="llm", name="litellm_chat_completion")
async def call_chat_completion(request_body: dict, *, timeout: float) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{settings.litellm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.litellm_master_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        resp.raise_for_status()
        return resp.json()


def _process_stream_inputs(inputs: dict) -> dict:
    # httpx client 不可序列化，也不该出现在 trace 里，只记录请求体
    return {"request_body": inputs.get("request_body")}


def _reduce_stream_chunks(chunks: list[dict]) -> dict:
    """把流式 chunk 列表聚合成和非流式 completion 相同的 {choices, usage} 形状。"""
    content_parts: list[str] = []
    tool_calls: dict[int, dict] = {}
    usage: dict | None = None
    finish_reason: str | None = None

    for chunk in chunks:
        choices = chunk.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                acc = tool_calls.setdefault(idx, {"id": "", "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    acc["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    acc["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    acc["function"]["arguments"] += fn["arguments"]
            finish_reason = choices[0].get("finish_reason") or finish_reason
        if chunk.get("usage"):
            usage = chunk["usage"]

    message: dict = {"role": "assistant", "content": "".join(content_parts)}
    if tool_calls:
        message["tool_calls"] = list(tool_calls.values())
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": usage or {},
    }


@traceable(
    run_type="llm",
    name="litellm_chat_completion_stream",
    reduce_fn=_reduce_stream_chunks,
    process_inputs=_process_stream_inputs,
)
async def stream_chat_completion(
    client: httpx.AsyncClient, request_body: dict
) -> AsyncGenerator[dict, None]:
    async with client.stream(
        "POST",
        f"{settings.litellm_base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.litellm_master_key}",
            "Content-Type": "application/json",
        },
        json=request_body,
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:].strip()
            if raw == "[DONE]":
                break
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue
