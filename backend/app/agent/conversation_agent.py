"""
ConversationAgent — 报告问答 AI 助手

Responsibilities:
- Accept a user question about a specific report.
- Build context from the report (plan_json, evidence_json, profile) within ~20K token budget.
- Perform scoped RAG: vector_search limited to the same province+year.
- Call LiteLLM streaming endpoint and yield tokens.
- Apply regex compliance check on the final assembled response.
- Never make over-promises; always cite evidence source IDs.

Flow (per message):
    load_report_context → [optional] vector_search → LLM streaming → compliance_check → yield
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx

from app.agent.nodes.compliance import check_compliance
from app.config import settings

logger = logging.getLogger(__name__)

_CONV_MODEL = "report-agent"  # reuse same virtual model as report_agent
_LLM_TIMEOUT = 60.0
_MAX_HISTORY_MESSAGES = 10  # trim to last N messages for context
_MAX_PLAN_JSON_CHARS = 8000
_MAX_EVIDENCE_CHARS = 3000

_SYSTEM_PROMPT = """\
你是"问津"AI 志愿助手。你的职责是基于已生成的志愿报告，回答考生或家长的探索性问题。

【硬性约束，必须严格遵守】
1. 禁止出现以下表述：保证录取、必中、精准录取、包过、保上、百分百录取、内部数据、代替填报、稳拿、必然上岸。
2. 每条建议必须有数据支撑，使用模糊表述时（如"概率较高"）须同时引用位次差数据。
3. 不允许对报告以外的院校或专业做出推荐。
4. 最终录取决定由考生和家长自主做出，AI 仅提供参考。
5. 如果无法基于已有报告数据回答，请明确说明"当前报告中没有该信息"，不要凭空编造。

【引用格式】
引用证据时使用 [来源:source_id] 格式，例如：根据郑州大学 2024 年招生章程 [来源:ev-001]。

【角色定位】
- 证据解读：解释推荐理由背后的位次/分数数据
- 风险说明：结合风险项说明注意事项
- 不做录取承诺，不做超出报告范围的对比
"""


def _build_context_block(
    plan_json: dict | None,
    evidence_json: list | None,
) -> str:
    """Compress report context to fit within token budget."""
    parts: list[str] = []

    if plan_json:
        plan_text = json.dumps(plan_json, ensure_ascii=False)
        if len(plan_text) > _MAX_PLAN_JSON_CHARS:
            plan_text = plan_text[:_MAX_PLAN_JSON_CHARS] + "...(已截断)"
        parts.append(f"【志愿方案 JSON】\n{plan_text}")

    if evidence_json:
        ev_text = json.dumps(evidence_json[:10], ensure_ascii=False)  # top-10 evidence
        if len(ev_text) > _MAX_EVIDENCE_CHARS:
            ev_text = ev_text[:_MAX_EVIDENCE_CHARS] + "...(已截断)"
        parts.append(f"【证据链（前10条）】\n{ev_text}")

    return "\n\n".join(parts)


def _trim_history(messages: list[dict]) -> list[dict]:
    """Keep only the last N turns to avoid huge prompts."""
    return messages[-_MAX_HISTORY_MESSAGES:]


def _compliance_check(text: str) -> tuple[bool, list[str]]:
    """Quick regex compliance check on generated response text."""
    issues = check_compliance(text)
    return len(issues) == 0, issues


def _sanitize_response(text: str, issues: list[str]) -> str:
    """Replace compliance-violating phrases with safe alternatives."""
    replacements = {
        r"保证录取": "有录取可能",
        r"必中": "有较大概率录取",
        r"精准录取": "预计录取",
        r"包过": "通过概率较高",
        r"保上": "安全边际较充足",
        r"百分百录取": "预计录取概率较高",
        r"稳拿": "有较大把握",
        r"必然上岸": "预计可以录取",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text


async def stream_conversation_response(
    *,
    plan_json: dict | None,
    evidence_json: list | None,
    history: list[dict],
    user_message: str,
    extra_context: str = "",
) -> AsyncGenerator[dict, None]:
    """
    Core streaming generator for ConversationAgent.

    Yields dicts:
        {"type": "token", "content": "..."}
        {"type": "citation", "source_id": "...", "text": "..."}
        {"type": "compliance_warning", "issues": [...]}
        {"type": "done", "full_response": "..."}
        {"type": "error", "message": "..."}
    """
    context_block = _build_context_block(plan_json, evidence_json)
    trimmed_history = _trim_history(history)

    # Build messages array
    system_content = _SYSTEM_PROMPT
    if context_block:
        system_content += f"\n\n【当前报告上下文】\n{context_block}"
    if extra_context:
        system_content += f"\n\n【补充检索结果】\n{extra_context}"

    messages = [{"role": "system", "content": system_content}]
    for msg in trimmed_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    full_response = ""
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{settings.litellm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.litellm_master_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _CONV_MODEL,
                    "messages": messages,
                    "max_tokens": 1200,
                    "temperature": 0.4,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        delta = chunk["choices"][0]["delta"]
                        token = delta.get("content") or ""
                        if token:
                            full_response += token
                            yield {"type": "token", "content": token}
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    except Exception as exc:
        logger.warning("ConversationAgent LLM call failed: %s", exc)
        fallback = "抱歉，AI 助手暂时无法响应，请稍后重试。"
        yield {"type": "token", "content": fallback}
        full_response = fallback

    # ── Compliance check on full assembled response ──
    passed, issues = _compliance_check(full_response)
    if not passed:
        full_response = _sanitize_response(full_response, issues)
        yield {"type": "compliance_warning", "issues": issues}

    # ── Extract citation references from response ──
    citation_pattern = re.compile(r"\[来源:([^\]]+)\]")
    for match in citation_pattern.finditer(full_response):
        source_id = match.group(1)
        yield {"type": "citation", "source_id": source_id, "text": match.group(0)}

    yield {
        "type": "done",
        "full_response": full_response,
        "created_at": datetime.now(UTC).isoformat(),
    }
