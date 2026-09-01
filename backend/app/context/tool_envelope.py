"""
工具结果统一信封 —— 对应 §10.2.6/§8.9。

intake_agent 的 SQL 工具（`_run_lookup_tool`）和文档检索工具（`_run_document_search`）
已经各自把 `ToolResponse`（`app/agent/tool_response.py`）序列化成
`{"status", "text", "data"}` 三态字典，`_format_tool_result_text`/
`_stream_document_synthesis` 直接消费这份字典生成回复文本，这部分不动。

这里补的是给 Context Builder/上下文清单看的统一视图：把同一份 `tool_result`
字典转成 `{status, key_fields, error, completeness_flag, source, as_of}`，只用于
manifest 观测，不影响发给用户的实际文本。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class ToolResultEnvelope:
    status: str  # SUCCESS/PARTIAL/ERROR，与 ToolResponse.status.value 对齐
    key_fields: dict[str, Any]
    error: str | None
    completeness_flag: bool  # True 表示结果完整覆盖了本次查询意图，可以直接作答
    source: str
    as_of: str


def to_context_envelope(tool_name: str, tool_result: dict) -> ToolResultEnvelope:
    status = tool_result.get("status", "ERROR")
    data = tool_result.get("data") or {}
    return ToolResultEnvelope(
        status=status,
        key_fields=data,
        error=tool_result.get("text") if status == "ERROR" else None,
        completeness_flag=status == "SUCCESS",
        source=tool_name,
        as_of=datetime.now(UTC).isoformat(),
    )
