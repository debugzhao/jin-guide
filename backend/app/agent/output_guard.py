"""面向用户输出的流式安全护栏。

模型输出必须先经过这里再发送给 SSE。护栏保留可能跨 chunk 的禁词前缀和未闭合的
引用标记，只有确认安全的文本才会放行，避免“完整响应检查通过前用户已经看见原文”。
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from app.agent.nodes.compliance import _FORBIDDEN, check_compliance, sanitize_text

_CITATION_PATTERN = re.compile(r"\[来源:([^\]]+)\]")
_CITATION_PREFIX = "[来源:"


def _longest_forbidden_prefix_suffix(text: str) -> int:
    """返回文本末尾与敏感词或引用标记开头重合的最长长度。"""
    longest = 0
    for word in (*_FORBIDDEN, _CITATION_PREFIX):
        max_length = min(len(text), len(word) - 1)
        for length in range(max_length, 0, -1):
            if text.endswith(word[:length]):
                longest = max(longest, length)
                break
    return longest


def sanitize_citations(text: str, allowed_source_ids: Iterable[str]) -> tuple[str, list[str]]:
    """移除不在当前证据白名单内的引用标记，并返回被移除的来源 ID。"""
    allowed = {str(source_id).strip() for source_id in allowed_source_ids if source_id}
    rejected: list[str] = []

    def replace(match: re.Match[str]) -> str:
        source_id = match.group(1).strip()
        if source_id in allowed:
            return f"[来源:{source_id}]"
        rejected.append(source_id)
        return ""

    return _CITATION_PATTERN.sub(replace, text), rejected


class StreamingOutputGuard:
    """在输出前完成禁词替换和引用白名单校验的有状态过滤器。"""

    def __init__(self, *, allowed_source_ids: Iterable[str] = ()) -> None:
        self._buffer = ""
        self._allowed_source_ids = {str(source_id).strip() for source_id in allowed_source_ids if source_id}
        self.compliance_issues: list[str] = []
        self.rejected_citations: list[str] = []

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buffer += text

        keep_length = _longest_forbidden_prefix_suffix(self._buffer)
        cut = len(self._buffer) - keep_length

        # 引用可能被模型拆成多个 token；闭合前整段保留，不能把未经校验的半个引用发给用户。
        last_open = self._buffer.rfind(_CITATION_PREFIX)
        last_close = self._buffer.rfind("]")
        if last_open > last_close:
            cut = min(cut, last_open)

        if cut <= 0:
            return ""
        safe_raw = self._buffer[:cut]
        self._buffer = self._buffer[cut:]
        return self._sanitize(safe_raw)

    def flush(self) -> str:
        safe_raw = self._buffer
        self._buffer = ""
        return self._sanitize(safe_raw)

    def _sanitize(self, text: str) -> str:
        for issue in check_compliance(text):
            if issue not in self.compliance_issues:
                self.compliance_issues.append(issue)
        sanitized = sanitize_text(text)
        sanitized, rejected = sanitize_citations(sanitized, self._allowed_source_ids)
        for source_id in rejected:
            if source_id not in self.rejected_citations:
                self.rejected_citations.append(source_id)
        return sanitized
