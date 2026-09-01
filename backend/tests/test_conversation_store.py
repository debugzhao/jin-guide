"""
conversation_store.py 的回源与并发安全回归测试 —— 对应
backend/docs/context/上下文模块评审.md §10.1「验证并固化已完成的正确性改造」。

覆盖范围：
  - hydrate_history_from_db：Redis 回源策略的共享实现（chat.py/intake_chat.py
    四个入口共用），命中/未命中两条路径是否正确回填 Redis
  - upsert_summary：数据库层 CAS（covered_through_seq = expected 时才更新）
    在并发冲突下是否安全放弃，而不是用旧结果覆盖别人已提交的新结果

不连真实 Postgres/Redis——ConversationMessage/ConversationSummary 用了
JSONB 列，sqlite 内存库无法编译（同 test_rules.py 的既有结论），这里改为
mock AsyncSession/Redis 客户端，只验证编排逻辑本身，与 test_reflection_agent.py
的既有测试风格一致。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.services import conversation_store as store


def _make_async_db() -> MagicMock:
    """AsyncSession 的最小 mock：execute/commit/rollback 是协程，add 是普通同步
    方法，与真实 AsyncSession API 保持一致——否则整个对象直接用 AsyncMock()
    会让本该同步的 db.add() 也变成协程，产生"never awaited"警告掩盖真正的
    断言失败。"""
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ── hydrate_history_from_db：Redis 回源共享策略 ─────────────────────────────

class TestHydrateHistoryFromDb:
    @pytest.mark.asyncio
    async def test_returns_empty_and_skips_refill_when_db_has_no_history(self, monkeypatch):
        """父行刚创建、还没有任何消息时：不应该写一次空列表进 Redis。"""
        monkeypatch.setattr(store, "load_recent_messages_from_db", AsyncMock(return_value=[]))
        append_mock = AsyncMock()
        monkeypatch.setattr(store, "append_history_to_redis", append_mock)

        result = await store.hydrate_history_from_db(
            AsyncMock(), "chat:history:report-1:user-1", parent_kind="report", parent_id="conv-1"
        )

        assert result == []
        append_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refills_redis_when_db_has_history(self, monkeypatch):
        """DB 命中时必须回填 Redis——这是 GET /chat/history、GET /intake/chat/history
        此前遗漏的一步（见函数 docstring），统一到这里后两个只读接口也会预热热层。"""
        messages = [{"role": "user", "content": "预算5万", "created_at": "2026-01-01T00:00:00+00:00"}]
        monkeypatch.setattr(store, "load_recent_messages_from_db", AsyncMock(return_value=messages))
        append_mock = AsyncMock()
        monkeypatch.setattr(store, "append_history_to_redis", append_mock)

        redis_key = "intake:history:owner-1:conv-1"
        result = await store.hydrate_history_from_db(
            AsyncMock(), redis_key, parent_kind="intake", parent_id="conv-1"
        )

        assert result == messages
        append_mock.assert_awaited_once_with(redis_key, messages)


# ── upsert_summary：数据库层 CAS ─────────────────────────────────────────────

class TestUpsertSummaryCas:
    @pytest.mark.asyncio
    async def test_update_conflict_is_discarded_without_overwriting(self):
        """expected_covered_through_seq 已经和数据库当前值不一致（被另一个并发
        任务先一步写入更新的摘要）时，rowcount=0，本次结果必须安全放弃：不能
        commit，也不能让 covered_through_seq 倒退。"""
        existing = SimpleNamespace(id="sum-1", covered_through_seq=26)
        select_result = SimpleNamespace(scalar_one_or_none=lambda: existing)
        update_result = SimpleNamespace(rowcount=0)

        db = _make_async_db()
        db.execute = AsyncMock(side_effect=[select_result, update_result])

        await store.upsert_summary(
            db,
            parent_kind="intake",
            parent_id="conv-1",
            summary_json={"confirmed_facts": ["旧结果"]},
            covered_through_seq=42,
            expected_covered_through_seq=10,  # 已经过期的旧覆盖位置
            source_model="kimi-k2.6",
            prompt_version="v1",
            tokens_before=None,
            tokens_after=None,
        )

        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_succeeds_when_expected_matches_current(self):
        """expected 和当前值一致时才真正提交，覆盖位置单调前进。"""
        existing = SimpleNamespace(id="sum-1", covered_through_seq=10)
        select_result = SimpleNamespace(scalar_one_or_none=lambda: existing)
        update_result = SimpleNamespace(rowcount=1)

        db = _make_async_db()
        db.execute = AsyncMock(side_effect=[select_result, update_result])

        await store.upsert_summary(
            db,
            parent_kind="intake",
            parent_id="conv-1",
            summary_json={"confirmed_facts": ["预算5万"]},
            covered_through_seq=26,
            expected_covered_through_seq=10,
            source_model="kimi-k2.6",
            prompt_version="v1",
            tokens_before=None,
            tokens_after=None,
        )

        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_first_summary_insert_conflict_is_discarded(self):
        """两个并发任务都判断"还没有摘要行"→都走 INSERT：唯一约束让后提交的
        一方在 commit 时报 IntegrityError，必须被吞掉而不是向上抛出中断
        best-effort 的后台任务。"""
        select_result = SimpleNamespace(scalar_one_or_none=lambda: None)

        db = _make_async_db()
        db.execute = AsyncMock(return_value=select_result)
        db.commit = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup key")))

        await store.upsert_summary(
            db,
            parent_kind="intake",
            parent_id="conv-1",
            summary_json={"confirmed_facts": ["预算5万"]},
            covered_through_seq=16,
            expected_covered_through_seq=0,
            source_model="kimi-k2.6",
            prompt_version="v1",
            tokens_before=None,
            tokens_after=None,
        )

        db.rollback.assert_awaited_once()
