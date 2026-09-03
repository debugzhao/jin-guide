"""
上下文清单 —— 对应 §3.9/§10.2.7。

先以结构化日志 best-effort 输出，不新增数据库表；沿用 `app/agent/context_budget.py`
的 Token 计数原语（tiktoken cl100k_base 近似估算），把原来两个 Agent 各自打的
扁平 `context_budget_snapshot` 日志（只统计 token）升级成带 included/truncated/
drop_reason 的清单（对应第九步"生成上下文清单"要记录的字段：来源、Token 数、
是否被裁剪、裁剪原因、预算是否触发降级）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

import structlog

from app.agent.context_budget import count_tokens
from app.context.tool_envelope import ToolResultEnvelope
from app.context.types import ContextItem

_logger = structlog.get_logger()
_FINGERPRINT_KEY = secrets.token_bytes(32)


def messages_key(messages: list[dict]) -> str:
    """进程内关联同一份消息；随机 HMAC 密钥不落日志，避免明文或可枚举的裸哈希。"""
    raw = json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()
    return hmac.new(_FINGERPRINT_KEY, raw, hashlib.sha256).hexdigest()[:24]


def _estimate(text: str) -> int | None:
    # 观测不能因为特殊 tokenizer 标记或其他计数错误中断聊天。
    try:
        return count_tokens(text)
    except Exception:
        return None


def _total(values: list[int | None]) -> int | None:
    return None if any(v is None for v in values) else sum(values)


def message_snapshot(messages: list[dict]) -> dict:
    """只记录最终消息形状，不记录正文、工具参数、URL、用户事实。"""
    shapes = [
        {
            "index": i,
            "role": m.get("role"),
            "content_chars": len(m.get("content") or ""),
            "content_tokens_estimate": _estimate(m.get("content") or ""),
            "tool_call_count": len(m.get("tool_calls") or []),
        }
        for i, m in enumerate(messages)
    ]
    return {
        "messages_key": messages_key(messages),
        "message_count": len(messages),
        "message_roles": [m.get("role") for m in messages],
        "messages": shapes,
        "message_content_tokens_estimate": _total([s["content_tokens_estimate"] for s in shapes]),
    }


def history_snapshot(history: list[dict], window: int) -> dict:
    selected = history[-window:]
    effective = [m for m in selected if m.get("role", "user") in ("user", "assistant") and m.get("content")]
    return {
        "loaded_messages": len(history),
        "window_limit": window,
        "selected_messages": len(selected),
        "emitted_messages": len(effective),
        "window_dropped_messages": len(history) - len(selected),
        "filtered_messages": len(selected) - len(effective),
    }


def structured_snapshot(original: dict | list, rendered: str, char_limit: int, item_limit: int | None = None) -> dict:
    def list_items(value):
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return sum(len(v) for v in value.values() if isinstance(v, list))
        return 0

    try:
        parsed = json.loads(rendered)
        valid = True
    except ValueError:
        parsed, valid = None, False
    return {
        "original_chars": len(json.dumps(original, ensure_ascii=False)),
        "rendered_chars": len(rendered),
        "char_limit": char_limit,
        "item_limit": item_limit,
        "original_direct_list_items": list_items(original),
        "rendered_direct_list_items": list_items(parsed) if valid else None,
        "json_valid": valid,
        "char_fallback": not valid,
    }


def build_manifest_entries(items: list[ContextItem]) -> list[dict]:
    entries = []
    for item in items:
        tokens = _estimate(item.content)
        entries.append({
            "source_type": item.source_type.value,
            "label": item.label,
            "trust_level": item.trust_level.value,
            "required": item.required,
            "tokens": tokens,
            "content_chars": len(item.content),
            "included": item.included and bool(item.content),
            "truncated": item.truncated,
            "drop_reason": item.drop_reason or ("empty_content" if not item.content else None),
        })
    return entries


def log_context_manifest(
    *,
    agent: str,
    items: list[ContextItem],
    degraded: bool = False,
    correlation_id: str | None = None,
    messages: list[dict] | None = None,
    history: dict | None = None,
    structured_sources: dict | None = None,
) -> list[dict]:
    """记录本轮上下文清单，返回 entries 供调用方需要时复用（比如测试断言）。

    `correlation_id` 传 `report_id`（报告问答）或 `conversation_id`（建档聊天）——
    没有这个字段时，端到端测试只能靠时间戳/顺序去猜哪条 `context_manifest` 日志
    对应哪次请求；有了它可以直接 `docker compose logs backend | grep <id>` 定位
    这一轮请求的完整上下文构成。
    """
    entries = build_manifest_entries(items)
    _logger.info(
        "context_manifest",
        agent=agent,
        correlation_id=correlation_id,
        total_tokens=_total([e["tokens"] for e in entries if e["included"]]),
        sources=entries,
        degraded=degraded,
        budget_mode="observe_only",
        hard_budget_enabled=False,
        token_estimator="cl100k_base_approximate",
        history=history,
        structured_sources=structured_sources,
        **(message_snapshot(messages) if messages is not None else {}),
    )
    return entries


def log_model_context(*, agent: str, messages: list[dict], correlation_id: str | None,
                      invocation_id: str, phase: str, tools: list[dict], output_budget: int) -> None:
    """紧贴真实发送点，包括 RAG 二次调用。估算不含协议开销、并非服务端 usage。"""
    _logger.info(
        "context_model_request", agent=agent, correlation_id=correlation_id,
        invocation_id=invocation_id, phase=phase,
        hard_budget_enabled=False, budget_mode="observe_only",
        tool_schema_count=len(tools),
        tool_schema_tokens_estimate=_estimate(json.dumps(tools, ensure_ascii=False)) if tools else 0,
        output_max_tokens=output_budget,
        token_estimator="cl100k_base_approximate",
        parent_messages_key=messages_key(messages[:-2]) if phase == "document_synthesis" else None,
        **message_snapshot(messages),
    )


def log_context_load(*, agent: str, correlation_id: str, history_source: str,
                     history_count: int, cached_answer: bool, summary_meta: dict | None,
                     summary_load_status: str) -> None:
    _logger.info(
        "context_turn_loaded", agent=agent, correlation_id=correlation_id,
        history_source=history_source, loaded_history_messages=history_count,
        answer_cache_hit=cached_answer, builder_will_run=not cached_answer,
        summary=summary_meta, summary_load_status=summary_load_status,
    )


def log_tool_envelope(
    *, agent: str, envelope: ToolResultEnvelope, correlation_id: str | None = None,
    messages: list[dict] | None = None,
) -> None:
    """记录一次工具调用的统一信封（对应 §8.9/§10.2.6）。

    跟 `log_context_manifest` 是两件事：manifest 记录"这轮实际发给模型的
    内容"，这里记录"工具刚刚返回了什么、是否完整"——SQL 工具的结果会被
    模板化成回复文本、不会再发回模型，不属于任何一次 messages 组装，但同样
    需要被观测到，否则没法回答"这轮回答依赖的工具调用是否完整成功"。
    """
    _logger.info(
        "tool_result_envelope",
        agent=agent,
        correlation_id=correlation_id,
        source=envelope.source,
        status=envelope.status,
        completeness_flag=envelope.completeness_flag,
        error_present=bool(envelope.error),
        # error 可能包含用户学校名等文本，只记录存在性。
        result_field_count=len(envelope.key_fields),
        result_chunk_count=len(envelope.key_fields.get("chunks") or []),
        completeness_basis="status_only",
        as_of_basis="envelope_created_at",
        messages_key=messages_key(messages) if messages is not None else None,
        as_of=envelope.as_of,
    )
