"""
IntakeAgent — 建档前 Chat-first 聊天 Agent。

取代旧版 `/profile/intent` 二分类接口：不再是"先分类再二选一"，而是一个真正的多轮
流式 chatbot，话题限定在高考志愿相关范围内，通过 function calling 在需要时查询
确定性数据，并在识别到建档意图时调用 `start_profile_capture` 信号工具——由前端
监听这个信号内联渲染建档表单，一次对话回合内同时完成"聊天"和"是否该建档"两件事。

Flow（每轮，只发一次流式请求，不做"先非流式分类再流式回答"的两段式，也不再为
工具调用发第二次请求——见下方"性能"说明）：
    第一次流式请求（带 tools，tool_choice=auto）
      → 无 tool_calls：content 增量即最终回复，边收边 yield token
      → 命中 start_profile_capture：不需要模型再生成正文，直接用固定文案 + 触发事件
      → 命中数据查询类工具：执行 SQL，把结构化结果直接模板化成自然语言（见
        `_format_tool_result_text`），不再发起第二次流式请求让模型复述

性能：kimi-k2.6 是推理模型，吐出真正 content 前会先流式输出一大段隐藏的
reasoning_content（思维链），这段耗时对用户不可见，体感就是"发了消息卡住不动"
（docs/疑问杂项.md「/api/v1/intake/chat 响应慢的原因与优化方向」）。本模块把
reasoning_content 也转发成 "thinking" 事件供前端展示过渡态/可展开的"AI 推理
过程"，经 `_ThinkingBuffer` 按自然语句片段做合规过滤后才吐出，不会把未经审查
的原始模型输出直接展示给用户。原来"工具调用后再发一次完整流式请求"的做法已经
去掉，改为上面提到的模板化，避免同一轮对话里付两次推理开销的钱、等两次的时间。
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
MAX_HISTORY_MESSAGES = 16
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

_THINKING_FLUSH_LEN = 30
_SENTENCE_ENDINGS = ("。", "！", "？", "\n", ".", "!", "?")


class _ThinkingBuffer:
    """
    reasoning_content 是逐字/逐词流式到达的，禁词有可能被拆在两个 chunk 之间
    （比如"保证"和"录取"分属两个 chunk），不能对每个到达的小 chunk 单独跑
    check_compliance——必须先攒够一个自然语句片段再整体检测+替换后才吐给前端，
    否则会漏检刚好被切在片段边界上的禁词。

    按句末标点或攒够 _THINKING_FLUSH_LEN 字符（先到者为准）切成小段落，只在这个
    粒度上做合规过滤——足以完整框住绝大多数禁词短语，又不用等整段思考结束才展示
    （那样就失去了"实时"的意义）。极小概率下禁词恰好被切在两个片段的边界上会漏检，
    这里接受这个残余风险：这只是一个默认收起的"AI 推理过程"展示面板，不是最终对
    用户负责的正式回复——正式回复 full_response 依然会完整走一遍 check_compliance，
    不受这里的分段方式影响。
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> str | None:
        self._buf += chunk
        if len(self._buf) >= _THINKING_FLUSH_LEN or any(p in chunk for p in _SENTENCE_ENDINGS):
            flushed = sanitize_text(self._buf)
            self._buf = ""
            return flushed
        return None

    def flush_remaining(self) -> str | None:
        if not self._buf:
            return None
        flushed = sanitize_text(self._buf)
        self._buf = ""
        return flushed


def _trim_history(messages: list[dict]) -> list[dict]:
    return messages[-MAX_HISTORY_MESSAGES:]


_SUMMARY_LABELS = {
    "confirmed_facts": "已确认信息",
    "preferences": "已表达偏好",
    "rejected_options": "已排除选项",
    "previous_decisions": "此前已做出的结论",
    "open_questions": "待跟进问题",
}


def _build_summary_block(summary: dict | None) -> str:
    """
    Render the structured incremental summary (see docs/memory-architecture.md
    §六 P2) covering messages that have already aged out of _trim_history's
    raw MAX_HISTORY_MESSAGES window, so facts stated early in a long intake
    conversation (budget, preferences, etc.) aren't silently forgotten once
    the turn that stated them scrolls out of view.
    """
    if not summary:
        return ""
    parts = []
    for key, label in _SUMMARY_LABELS.items():
        values = summary.get(key) or []
        if values:
            parts.append(f"{label}：" + "；".join(str(v) for v in values))
    return "\n".join(parts)


def _build_messages(history: list[dict], user_message: str, summary: dict | None = None) -> list[dict]:
    system_content = _SYSTEM_PROMPT
    summary_block = _build_summary_block(summary)
    if summary_block:
        system_content += f"\n\n【早于当前对话窗口的历史摘要】\n{summary_block}"

    messages = [{"role": "system", "content": system_content}]
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
        # 1200 在复杂续写场景（"继续执行"这类要求补完长回答）下偶尔不够用——
        # kimi-k2.6 有时会把答案草稿写在 reasoning_content 里，还没切到正式
        # content 就把预算耗完，导致用户什么都收不到。2000 留更多余量，
        # 兜底 fallback 见下方 `if not full_response` 分支。
        "max_tokens": 2000,
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


def _format_tool_result_text(name: str, args: dict, tool_result: dict) -> str:
    """
    把工具查询的结构化 data 直接模板化成自然语言，取代原来"执行完工具后再发一次
    完整流式请求让模型复述"的做法——第二次调用同样要完整走一遍 kimi-k2.6 的隐藏
    思维链开销，是 tool_score/tool_subject/tool_compare 场景耗时接近翻倍的主因
    （见 docs/疑问杂项.md「/api/v1/intake/chat 响应慢的原因与优化方向」）。

    非 SUCCESS 状态（ERROR/PARTIAL）直接用工具自带的 text，已经是人类可读的
    提示（比如"未找到院校「XXX」"），不需要模板化。
    """
    status = tool_result.get("status")
    data = tool_result.get("data") or {}

    if status != "SUCCESS":
        return tool_result.get("text", "查询暂时不可用")

    if name == "lookup_university_score":
        tags = "、".join(t for t, on in (("985", data.get("is_985")), ("211", data.get("is_211"))) if on)
        header = f"{data.get('university_name', '')}"
        if data.get("city") or tags:
            header += f"（{data.get('city', '')}{'，' + tags if tags else ''}）"
        province = args.get("province", "")
        batch = args.get("batch") or "本科批"
        lines = [f"{header}在 {province}{batch} 的录取情况："]
        for r in data.get("records", []):
            lines.append(
                f"- {r.get('year')}年：最低分 {r.get('min_score')} 分（位次 {r.get('min_rank')}），"
                f"平均分 {r.get('avg_score')} 分（位次 {r.get('avg_rank')}）"
            )
        return "\n".join(lines)

    if name == "lookup_subject_requirement":
        lines = [f"{data.get('university_name', '')} 选科要求："]
        for r in data.get("requirements", []):
            required = "、".join(r.get("required_subjects") or []) or "无必选"
            optional = r.get("optional_subjects") or []
            optional_desc = (
                f"{'、'.join(optional)}中选{r.get('optional_required_count')}门" if optional else ""
            )
            restricted = "、".join(r.get("restricted_subjects") or []) or "无"
            lines.append(
                f"- {r.get('major_name')}：必选 {required}"
                + (f"；{optional_desc}" if optional_desc else "")
                + f"；限制科目：{restricted}"
            )
        return "\n".join(lines)

    if name == "compare_universities":
        province = args.get("province", "")
        batch = args.get("batch") or "本科批"
        lines = [f"对比结果（{province}{batch}）："]
        for u in data.get("universities", []):
            tags = "、".join(t for t, on in (("985", u.get("is_985")), ("211", u.get("is_211"))) if on)
            required = "、".join(u.get("required_subjects") or []) or "无必选科目"
            lines.append(
                f"- {u.get('university_name')}（{u.get('city', '')}{'，' + tags if tags else ''}）："
                f"{u.get('year')}年最低分 {u.get('min_score')} 分/位次 {u.get('min_rank')}，选科要求：{required}"
            )
        if data.get("not_found"):
            lines.append(f"未找到：{'、'.join(data['not_found'])}")
        return "\n".join(lines)

    return tool_result.get("text", "")


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
    summary: dict | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Core streaming generator for IntakeAgent.

    `summary` is the structured incremental summary covering messages that
    have already aged out of the raw history window (see P2) — pass None to
    fall back to the pre-P2 behavior of only ever seeing the last
    MAX_HISTORY_MESSAGES turns.

    Yields dicts:
        {"type": "thinking", "content": "..."}  (kimi-k2.6 隐藏思维链，供前端展示过渡态)
        {"type": "token", "content": "..."}
        {"type": "trigger_profile_capture"}
        {"type": "compliance_warning", "issues": [...]}
        {"type": "done", "full_response": "..."}
        {"type": "error", "message": "..."}
    """
    messages = _build_messages(history, user_message, summary)
    full_response = ""

    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            tool_calls_acc: dict[int, dict] = {}
            finish_reason: str | None = None
            thinking_buffer = _ThinkingBuffer()

            async for chunk in _stream_chat(client, messages, use_tools=True):
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason") or finish_reason

                thinking = delta.get("reasoning_content")
                if thinking:
                    flushed = thinking_buffer.feed(thinking)
                    if flushed:
                        yield {"type": "thinking", "content": flushed}

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

            remaining_thinking = thinking_buffer.flush_remaining()
            if remaining_thinking:
                yield {"type": "thinking", "content": remaining_thinking}

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

                # 查询类工具的结果直接模板化成自然语言，不再发起第二次完整流式请求
                # 让模型复述——第二次调用会重新付出一遍 kimi-k2.6 的隐藏思维链开销，
                # 是工具调用场景耗时接近翻倍的主因，见 _format_tool_result_text 的注释。
                for c in calls:
                    try:
                        args = json.loads(c["arguments"]) if c["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_result = await _execute_tool_call(c["name"], c["arguments"])
                    text = _format_tool_result_text(c["name"], args, tool_result)
                    separator = "\n\n" if full_response else ""
                    full_response += separator + text
                    yield {"type": "token", "content": separator + text}

            if not full_response:
                # kimi-k2.6 有时会把整段答案的草稿写在 reasoning_content 里，
                # 还没来得及切到真正的 content 就已经耗尽 max_tokens——尤其是
                # "把之前被截断的内容补完"这类复杂续写场景。这种情况下用户
                # 什么都收不到（thinking 事件里其实已经有草稿，但那只是过渡态
                # 展示，不能当正式回复），必须给一个明确的兜底提示，而不是让
                # 前端收到一个空的 done 事件、什么反应都没有。
                full_response = "这个问题有点复杂，我还没组织完答案就到达长度上限了，可以换个更具体的问法，或者拆成几个小问题分别问我～"
                yield {"type": "token", "content": full_response}

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
