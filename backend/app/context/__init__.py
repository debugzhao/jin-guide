"""
统一 Context Builder —— 见 backend/docs/context/上下文模块评审.md §10.2。

`conversation_agent.py`（报告问答）和 `intake_agent.py`（建档前聊天）此前各自
手写历史裁剪、摘要拼接、报告/证据字符截断和 Token 统计，逻辑高度相似但不完全
一致。这个包把这些公共部分收敛成唯一实现：两个 Agent 模块只保留各自独有的业务
逻辑（system prompt 渲染、工具定义、流式生成编排），组装环节改为调用这里的
共享函数。

对外常用符号在这里重新导出，方便调用方一次性 import。
"""
from __future__ import annotations

from app.context.assembler import assemble_messages, wrap_item
from app.context.budget import TokenBudgetAllocator
from app.context.config import AgentContextConfig
from app.context.manifest import log_context_manifest, log_tool_envelope
from app.context.tool_envelope import ToolResultEnvelope, to_context_envelope
from app.context.trimming import (
    DEFAULT_SUMMARY_LABELS,
    render_summary_block,
    trim_history,
    truncate_structured,
)
from app.context.types import ContextItem, SourceType, TrustLevel

__all__ = [
    "AgentContextConfig",
    "ContextItem",
    "SourceType",
    "TrustLevel",
    "TokenBudgetAllocator",
    "ToolResultEnvelope",
    "to_context_envelope",
    "DEFAULT_SUMMARY_LABELS",
    "trim_history",
    "render_summary_block",
    "truncate_structured",
    "assemble_messages",
    "wrap_item",
    "log_context_manifest",
    "log_tool_envelope",
]
