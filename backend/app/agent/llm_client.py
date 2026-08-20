"""
LangGraph 节点调用 LiteLLM 网关的统一入口。

report_agent/profile_agent/reflection_agent 原先各自手写 httpx POST，调用完全
脱离 LangSmith 的 tracing 上下文——LangGraph 节点执行会自动生成父 run，但节点
内部这次裸 httpx 调用不会作为子 run 挂上去，trace 里只看到节点耗时，看不到
prompt/completion/token。这里用 @traceable(run_type="llm") 包一层：函数执行时
正处于 LangGraph 节点的活跃 trace 上下文内，会被自动挂成子 run；返回原始
completion JSON（含 usage 字段）而不是提取后的纯文本，LangSmith 按 OpenAI 兼容
格式识别 usage 并汇总到父 run 的 token 统计上。
"""
from __future__ import annotations

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
