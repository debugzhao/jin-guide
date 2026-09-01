"""
admin.py::_summary_lag_bucket 的分桶计算回归测试——对应
backend/docs/context/上下文模块评审.md §10.1「记录摘要失败、冲突、积压和
补偿状态」这一项：现有摘要失败只落 structlog 不落库，只能从
covered_through_seq 与最新消息 seq 的差值反推"落后"，这里验证反推的数学
本身没错（整除分桶、"3+"合并、never_summarized_but_due 判定），不连真实
Postgres（同 test_conversation_store.py 顶部注释的理由）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.api.v1.admin import _summary_lag_bucket


class _FakeRows:
    def __init__(self, rows: list[tuple[int, int | None]]):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_lag_bucket_math(monkeypatch):
    # (latest_seq, covered_through_seq)：
    #   (10, 10) -> 落后 0 条 -> 分桶 0
    #   (26, 10) -> 落后 16 条，window=16 -> 整除 1 -> 分桶 1
    #   (58, 10) -> 落后 48 条 -> 整除 3 -> 分桶 "3+"
    #   (20, None) -> 从未生成过摘要，且 20 >= window(16) -> due
    #   (5, None)  -> 从未生成过摘要，但 5 < window(16) -> 不算 due（天然还不需要摘要）
    rows = [(10, 10), (26, 10), (58, 10), (20, None), (5, None)]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeRows(rows))

    bucket = await _summary_lag_bucket(db, parent_kind="intake", window_size=16)

    assert bucket.total_conversations == 5
    # 分桶：(10,10)->0, (26,10)->1, (58,10)->3+, (20,None)->1, (5,None)->0
    assert bucket.lag_windows_distribution == {"0": 2, "1": 2, "2": 0, "3+": 1}
    assert bucket.never_summarized_but_due == 1
