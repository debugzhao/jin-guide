"""
统一上下文数据结构 —— 见 backend/docs/context/上下文模块评审.md §3.2/§9.4/§10.2.2。

两个 Agent 原本各自把"报告数据""摘要""检索资料"直接拼成字符串再决定要不要包一层
`wrap_untrusted_context`。这里补一层轻量元数据（来源类型、信任等级、是否被裁剪），
让 assembler/manifest 可以在不重新解析字符串内容的前提下，统一决定包装方式和
清单展示，不影响最终发给模型的文本本身。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceType(str, Enum):
    """对应 §2.1 的上下文来源分类。"""

    SYSTEM = "system"
    STATE = "state"  # 报告/方案等结构化业务数据（plan_json、evidence_json）
    SUMMARY = "summary"
    RAG = "rag"
    HISTORY = "history"
    CURRENT_REQUEST = "current_request"
    TOOL_RESULT = "tool_result"


class TrustLevel(str, Enum):
    """对应 §9.4 推荐的信任模型。"""

    TRUSTED_INSTRUCTION = "trusted_instruction"  # System，可以定义行为
    TRUSTED_DATA = "trusted_data"  # 已确认业务数据，只能提供事实，不升级为指令
    UNTRUSTED_USER = "untrusted_user"  # 当前请求/历史原文
    UNTRUSTED_MEMORY = "untrusted_memory"  # 摘要
    UNTRUSTED_EXTERNAL = "untrusted_external"  # RAG/检索片段
    TOOL_RESULT = "tool_result"  # 工具返回结果


@dataclass
class ContextItem:
    """一份候选上下文内容及其元数据（对应 §3.2）。

    `content` 是已完成结构化裁剪、但尚未做不可信数据包装的最终文本；`prefix`
    是拼在包装块前面的固定说明文字（比如"以下内容由系统提供…"），由构造方
    提供，因为不同 Agent 对同一类来源的措辞可能不同，不适合在 assembler 里
    硬编码成查找表。是否需要包装由 `trust_level` 决定，具体包装动作统一在
    `assembler.wrap_item` 里做。
    """

    source_type: SourceType
    trust_level: TrustLevel
    label: str  # manifest/日志展示的来源名，同时是 wrap_untrusted_context 的 tag
    content: str
    prefix: str = ""
    required: bool = False  # 必需来源缺失时不能静默丢弃（对应 §9.6）
    included: bool = True
    truncated: bool = False
    drop_reason: str | None = None
    token_cost: int = 0
