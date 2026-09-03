"""
上下文清单 —— 对应 §3.9/§10.2.7。

先以结构化日志 best-effort 输出，不新增数据库表；沿用 `app/agent/context_budget.py`
的 Token 计数原语（tiktoken cl100k_base 近似估算），把原来两个 Agent 各自打的
扁平 `context_budget_snapshot` 日志（只统计 token）升级成带 included/truncated/
drop_reason 的清单（对应第九步"生成上下文清单"要记录的字段：来源、Token 数、
是否被裁剪、裁剪原因、预算是否触发降级）。
"""
from __future__ import annotations

import structlog

from app.agent.context_budget import count_tokens
from app.context.tool_envelope import ToolResultEnvelope
from app.context.types import ContextItem

_logger = structlog.get_logger()


def build_manifest_entries(items: list[ContextItem]) -> list[dict]:
    entries = []
    for item in items:
        item.token_cost = count_tokens(item.content)
        entries.append({
            "source_type": item.source_type.value,
            "label": item.label,
            "trust_level": item.trust_level.value,
            "tokens": item.token_cost,
            "included": item.included,
            "truncated": item.truncated,
            "drop_reason": item.drop_reason,
        })
    return entries


def log_context_manifest(
    *,
    agent: str,
    items: list[ContextItem],
    degraded: bool = False,
    correlation_id: str | None = None,
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
        total_tokens=sum(e["tokens"] for e in entries if e["included"]),
        sources=entries,
        degraded=degraded,
    )
    return entries


def log_tool_envelope(
    *, agent: str, envelope: ToolResultEnvelope, correlation_id: str | None = None
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
        error=envelope.error,
        as_of=envelope.as_of,
    )
