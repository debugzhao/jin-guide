"""
每个 Agent 声明自己的上下文配置（历史窗口、结构化裁剪配额、摘要字段），不再
各自散落成模块级常量 —— 对应 §10.2.3。

数值保持和迁移前完全一致（历史窗口 10/16 条、`plan_json` 8000 字符、证据 10 条
+ 3000 字符），迁移只挪动常量的定义位置，不调整业务参数，避免"逻辑收敛"和
"参数调整"两类改动混在一次改动里排查问题（见 §10.2.9 本阶段不做）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.context.trimming import DEFAULT_SUMMARY_LABELS


@dataclass(frozen=True)
class AgentContextConfig:
    agent_name: str
    max_history_messages: int
    summary_labels: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SUMMARY_LABELS))
    max_plan_json_chars: int | None = None
    max_evidence_chars: int | None = None
    max_evidence_items: int | None = None


REPORT_CONVERSATION_CONFIG = AgentContextConfig(
    agent_name="conversation_agent",
    max_history_messages=10,
    max_plan_json_chars=8000,
    max_evidence_chars=3000,
    max_evidence_items=10,
)

INTAKE_CHAT_CONFIG = AgentContextConfig(
    agent_name="intake_agent",
    max_history_messages=16,
)
