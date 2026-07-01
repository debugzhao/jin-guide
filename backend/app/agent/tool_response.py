"""
ToolResponse 三态协议 — 问津 Agent 工具层统一返回类型。
所有工具函数返回 ToolResponse，替代裸 dict，供 Agent 节点做一致性处理。

参考 HelloAgents ToolResponse 设计（Section 10.8）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


@dataclass
class ToolResponse:
    status: ToolStatus
    text: str                          # LLM/人可读摘要
    data: dict[str, Any]               # 结构化负载
    error_info: dict[str, Any] | None = field(default=None)
    stats: dict[str, Any] | None = field(default=None)   # latency_ms, token 消耗等
    context: dict[str, Any] | None = field(default=None) # 调用参数/环境信息

    # ── 工厂方法 ────────────────────────────────────────────────────

    @classmethod
    def success(
        cls,
        text: str,
        data: dict[str, Any],
        stats: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> "ToolResponse":
        return cls(status=ToolStatus.SUCCESS, text=text, data=data, stats=stats, context=context)

    @classmethod
    def partial(
        cls,
        text: str,
        data: dict[str, Any],
        stats: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> "ToolResponse":
        return cls(status=ToolStatus.PARTIAL, text=text, data=data, stats=stats, context=context)

    @classmethod
    def error(
        cls,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> "ToolResponse":
        return cls(
            status=ToolStatus.ERROR,
            text=message,
            data=data or {},
            error_info={"code": code, "message": message},
            context=context,
        )

    # ── 状态判断便捷属性 ────────────────────────────────────────────

    @property
    def is_success(self) -> bool:
        return self.status == ToolStatus.SUCCESS

    @property
    def is_partial(self) -> bool:
        return self.status == ToolStatus.PARTIAL

    @property
    def is_error(self) -> bool:
        return self.status == ToolStatus.ERROR

    @property
    def is_usable(self) -> bool:
        """SUCCESS 或 PARTIAL 均视为可用（后者携带降级说明）。"""
        return self.status in (ToolStatus.SUCCESS, ToolStatus.PARTIAL)

    # ── 序列化 ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "text": self.text,
            "data": self.data,
            "error_info": self.error_info,
            "stats": self.stats,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolResponse":
        return cls(
            status=ToolStatus(d["status"]),
            text=d.get("text", ""),
            data=d.get("data", {}),
            error_info=d.get("error_info"),
            stats=d.get("stats"),
            context=d.get("context"),
        )

    def __repr__(self) -> str:
        return f"ToolResponse({self.status.value}, {self.text[:60]!r})"
