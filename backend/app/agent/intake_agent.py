"""
IntakeAgent — 建档前 Chat-first 聊天 Agent。

取代旧版 `/profile/intent` 二分类接口：不再是"先分类再二选一"，而是一个真正的多轮
流式 chatbot，话题限定在高考志愿相关范围内，通过 function calling 在需要时查询
确定性数据，并在识别到建档意图时调用 `start_profile_capture` 信号工具——由前端
监听这个信号内联渲染建档表单，一次对话回合内同时完成"聊天"和"是否该建档"两件事。

Flow（每轮，均为流式请求，不做"先非流式分类再流式回答"的两段式）：
    第一次流式请求（带 tools，tool_choice=auto）
      → 无 tool_calls：content 增量即最终回复，边收边 yield token
      → 命中 start_profile_capture：不需要模型再生成正文，直接用固定文案 + 触发事件
      → 命中数据查询类工具：执行 SQL，把结果塞回 messages，再发起一次流式请求
        （这次不带 tools，强制模型基于查询结果产出自然语言）
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.agent.nodes.compliance import _FORBIDDEN, check_compliance, sanitize_text
from app.config import settings

logger = logging.getLogger(__name__)

_INTAKE_MODEL = "intake-agent"
_LLM_TIMEOUT = 60.0
_MAX_HISTORY_MESSAGES = 16
_START_PROFILE_ACK = "好的，我们先把生成报告必须依赖的基础信息填一下～"

_SYSTEM_PROMPT = f"""\
你是"问津"AI 志愿助手。你只回答与高考志愿填报直接相关的问题，包括：
- 查询高校信息（位置、性质、985/211/双一流、学费）
- 查询历年录取分数线、位次
- 查询专业选科要求、体检限制
- 对比多所高校的录取分数和选科要求
- 解读一分一段表、批次政策、志愿填报规则
- 引导用户开始建档、生成志愿报告

【工具使用规则，必须严格遵守】
1. 涉及具体分数、位次、选科要求等事实性数据时，必须调用工具查询，禁止凭记忆直接回答数字。
2. 工具查不到数据时，如实告诉用户"暂无该数据"，不要编造。
3. 当用户明确表达"开始建档""生成报告""帮我推荐/测算能上的学校"这类意图时，调用
   start_profile_capture，不要自己编造推荐结果或分数线。

【话题边界】
如果用户的问题与高考志愿无关（写代码、闲聊八卦、其他学科作业、时事新闻等），礼貌拒绝
并引导回志愿相关话题，不要跑题作答。

【硬性约束】
禁止出现以下表述：{"、".join(_FORBIDDEN)}。
最终录取决定由考生和家长自主做出，你只提供参考，不做录取承诺。
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_university_score",
            "description": "查询某所高校在某个省份的历年高考录取分数线和位次，用于回答'XX大学在XX省多少分能上'这类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "university_name": {"type": "string", "description": "高校名称，如'浙江大学'"},
                    "province": {"type": "string", "description": "招生省份，如'河南'"},
                    "batch": {"type": "string", "description": "批次，不传默认本科批"},
                    "year": {"type": "integer", "description": "年份，不传则返回历年全部数据"},
                },
                "required": ["university_name", "province"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_subject_requirement",
            "description": "查询某所高校（某个专业）的选科要求和体检限制。",
            "parameters": {
                "type": "object",
                "properties": {
                    "university_name": {"type": "string"},
                    "major_name": {"type": "string", "description": "专业名称，不传则返回该校所有专业的选科要求"},
                },
                "required": ["university_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_universities",
            "description": "对比多所高校在同一省份的录取分数、位次和选科要求，用于'A和B哪个好考/怎么选'这类对比问题。只返回结构化数据，不含培养方向/师资等定性介绍。",
            "parameters": {
                "type": "object",
                "properties": {
                    "university_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-5 所高校名称",
                    },
                    "province": {"type": "string"},
                    "batch": {"type": "string", "description": "批次，不传默认本科批"},
                },
                "required": ["university_names", "province"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_profile_capture",
            "description": "当用户明确表达想要开始填写志愿建档信息、生成志愿报告、或想知道自己能上什么大学/要推荐时调用。调用后前端会展示建档表单，你不需要再回答具体推荐结果。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

_TOOL_NAMES = {t["function"]["name"] for t in _TOOLS}


def _trim_history(messages: list[dict]) -> list[dict]:
    return messages[-_MAX_HISTORY_MESSAGES:]


def _build_messages(history: list[dict], user_message: str) -> list[dict]:
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for msg in _trim_history(history):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


async def _stream_chat(
    client: httpx.AsyncClient, messages: list[dict], *, use_tools: bool
) -> AsyncGenerator[dict, None]:
    payload = {
        "model": _INTAKE_MODEL,
        "messages": messages,
        "max_tokens": 1200,
        "temperature": 1,
        "stream": True,
    }
    if use_tools:
        payload["tools"] = _TOOLS
        payload["tool_choice"] = "auto"

    async with client.stream(
        "POST",
        f"{settings.litellm_base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.litellm_master_key}",
            "Content-Type": "application/json",
        },
        json=payload,
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


def _run_lookup_tool(name: str, args: dict) -> dict:
    """同步执行确定性 SQL 查询工具（在 asyncio.to_thread 里跑），返回可 JSON 序列化的结果。"""
    from app.database import SyncSessionLocal
    from app.engine.school_lookup import (
        compare_universities,
        lookup_subject_requirement,
        lookup_university_score,
    )

    with SyncSessionLocal() as db:
        if name == "lookup_university_score":
            result = lookup_university_score(db, **args)
        elif name == "lookup_subject_requirement":
            result = lookup_subject_requirement(db, **args)
        elif name == "compare_universities":
            result = compare_universities(db, **args)
        else:
            return {"status": "ERROR", "text": f"未知工具 {name}", "data": {}}

    return {"status": result.status.value, "text": result.text, "data": result.data}


async def _execute_tool_call(name: str, arguments_json: str) -> dict:
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return {"status": "ERROR", "text": "工具参数解析失败", "data": {}}

    if name not in _TOOL_NAMES or name == "start_profile_capture":
        return {"status": "ERROR", "text": f"未知工具 {name}", "data": {}}

    try:
        return await asyncio.to_thread(_run_lookup_tool, name, args)
    except TypeError as exc:
        # 模型传的参数名/类型和工具签名对不上时，明确告诉模型而不是让请求整体失败
        return {"status": "ERROR", "text": f"工具参数不合法：{exc}", "data": {}}
    except Exception as exc:
        logger.warning("intake tool %s execution failed: %s", name, exc)
        return {"status": "ERROR", "text": "查询暂时不可用，请稍后重试", "data": {}}


async def stream_intake_response(
    *,
    history: list[dict],
    user_message: str,
) -> AsyncGenerator[dict, None]:
    """
    Core streaming generator for IntakeAgent.

    Yields dicts:
        {"type": "token", "content": "..."}
        {"type": "trigger_profile_capture"}
        {"type": "compliance_warning", "issues": [...]}
        {"type": "done", "full_response": "..."}
        {"type": "error", "message": "..."}
    """
    messages = _build_messages(history, user_message)
    full_response = ""

    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            tool_calls_acc: dict[int, dict] = {}
            finish_reason: str | None = None

            async for chunk in _stream_chat(client, messages, use_tools=True):
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason") or finish_reason

                token = delta.get("content")
                if token:
                    full_response += token
                    yield {"type": "token", "content": token}

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    acc = tool_calls_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        acc["name"] = fn["name"]
                    if fn.get("arguments"):
                        acc["arguments"] += fn["arguments"]

            if finish_reason == "tool_calls" and tool_calls_acc:
                calls = list(tool_calls_acc.values())

                if any(c["name"] == "start_profile_capture" for c in calls):
                    # 模型有时会在同一轮里既输出一句话又调用工具；已经有话就不再叠加固定文案，
                    # 避免出现"模型的话 + 写死的话"重复两句。
                    if not full_response:
                        full_response = _START_PROFILE_ACK
                        yield {"type": "token", "content": full_response}
                    yield {"type": "trigger_profile_capture"}
                    yield {"type": "done", "full_response": full_response}
                    return

                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {"name": c["name"], "arguments": c["arguments"]},
                            }
                            for c in calls
                        ],
                    }
                )
                for c in calls:
                    tool_result = await _execute_tool_call(c["name"], c["arguments"])
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": c["id"],
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )

                async for chunk in _stream_chat(client, messages, use_tools=False):
                    choice = (chunk.get("choices") or [{}])[0]
                    token = choice.get("delta", {}).get("content")
                    if token:
                        full_response += token
                        yield {"type": "token", "content": token}

            issues = check_compliance(full_response)
            if issues:
                full_response = sanitize_text(full_response)
                yield {"type": "compliance_warning", "issues": issues}

            yield {"type": "done", "full_response": full_response}

    except Exception as exc:
        logger.warning("IntakeAgent LLM call failed: %s", exc)
        fallback = "抱歉，AI 助手暂时无法响应，请稍后重试。"
        yield {"type": "token", "content": fallback}
        yield {"type": "done", "full_response": fallback}
