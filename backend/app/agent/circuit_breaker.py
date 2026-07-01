"""
CircuitBreaker — 外部调用熔断保护。
防止 Cohere Rerank / LiteLLM Proxy / pgvector 级联故障。

参考 HelloAgents CircuitBreaker 设计（Section 10.8）。

熔断阈值：连续 failure_threshold 次 ERROR → 开路（Open）
恢复超时：recovery_timeout 秒后自动转为半开路（Half-Open），
         下次调用成功则关路（Closed），失败则重新开路。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.tool_response import ToolResponse


class BreakerState(str, Enum):
    CLOSED = "CLOSED"        # 正常，允许调用
    OPEN = "OPEN"            # 熔断，拒绝调用
    HALF_OPEN = "HALF_OPEN"  # 恢复中，允许一次试探


@dataclass
class _BreakerEntry:
    state: BreakerState = BreakerState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0


class CircuitBreaker:
    """
    线程安全不保证（LangGraph Worker 是单进程协程，无需锁）。
    如部署到多进程，需迁移状态到 Redis。
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 300.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._entries: dict[str, _BreakerEntry] = {}

    def _get(self, tool_name: str) -> _BreakerEntry:
        if tool_name not in self._entries:
            self._entries[tool_name] = _BreakerEntry()
        return self._entries[tool_name]

    def is_open(self, tool_name: str) -> bool:
        """
        返回 True 表示熔断器开路 → 调用方应走降级路径，不发起真实调用。
        内部自动实现 lazy 恢复：超过 recovery_timeout 后转为 HALF_OPEN。
        """
        entry = self._get(tool_name)

        if entry.state == BreakerState.OPEN:
            elapsed = time.monotonic() - entry.last_failure_time
            if elapsed >= self._recovery_timeout:
                entry.state = BreakerState.HALF_OPEN
                return False  # 允许一次试探
            return True       # 仍在熔断冷却期

        return False  # CLOSED / HALF_OPEN → 允许调用

    def record_result(self, tool_name: str, response: "ToolResponse") -> None:
        """根据工具返回更新熔断状态。"""
        from app.agent.tool_response import ToolStatus

        entry = self._get(tool_name)

        if response.status == ToolStatus.ERROR:
            entry.failure_count += 1
            entry.last_failure_time = time.monotonic()
            if entry.failure_count >= self._failure_threshold:
                entry.state = BreakerState.OPEN
        else:
            # SUCCESS 或 PARTIAL 均视为成功，重置计数
            entry.failure_count = 0
            entry.state = BreakerState.CLOSED

    def get_state(self, tool_name: str) -> BreakerState:
        """查询当前状态（用于监控/日志）。"""
        return self._get(tool_name).state

    def reset(self, tool_name: str) -> None:
        """手动重置（测试或运维用）。"""
        if tool_name in self._entries:
            del self._entries[tool_name]


# ── 全局单例（Worker 进程内共享） ───────────────────────────────────
#   保护三个外部调用点（PRD Section 10.8）
_default_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=300.0)


def get_circuit_breaker() -> CircuitBreaker:
    """获取全局熔断器实例。"""
    return _default_breaker
