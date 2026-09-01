"""
conversation_summary.py 的分布式锁与窗口批量推进回归测试 —— 对应
backend/docs/context/上下文模块评审.md §10.1「验证并固化已完成的正确性改造」。

覆盖范围：
  - maybe_generate_summary：Redis 分布式锁互斥（抢不到锁直接跳过，不重复
    生成）、以及无论生成成功/异常都必须释放锁、关闭连接（不能造成锁泄漏或
    连接泄漏）
  - _generate_summary：只有攒够一整个窗口的新消息才触发；即使积压超过一个
    窗口，每次也只推进一个窗口，不会因为服务中断后攒了几轮积压就一次性
    全部追平

不连真实 Redis/Postgres，理由同 test_conversation_store.py 顶部注释。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import conversation_summary as summary_mod


class _FakeAsyncSessionCm:
    """`async with async_session_maker() as db:` 的最小替身，直接把预先构造
    好的 fake db 交出去，__aexit__ 不做真实的 commit/rollback。"""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc_info):
        return False


def _fake_redis(*, acquired: bool) -> AsyncMock:
    redis_client = AsyncMock()
    redis_client.set = AsyncMock(return_value=(True if acquired else None))
    redis_client.eval = AsyncMock(return_value=1 if acquired else 0)
    redis_client.aclose = AsyncMock()
    return redis_client


# ── maybe_generate_summary：分布式锁 ─────────────────────────────────────────

class TestSummaryLock:
    @pytest.mark.asyncio
    async def test_skips_generation_when_lock_is_busy(self, monkeypatch):
        """另一个并发的 BackgroundTasks 已经持有同一 (parent_kind, parent_id)
        的锁时，本次直接跳过——不能两边各自读到同一份旧摘要再互相覆盖。"""
        redis_client = _fake_redis(acquired=False)
        monkeypatch.setattr(summary_mod.aioredis, "from_url", lambda *a, **k: redis_client)
        generate_mock = AsyncMock()
        monkeypatch.setattr(summary_mod, "_generate_summary", generate_mock)

        await summary_mod.maybe_generate_summary("intake", "conv-1", window_size=16)

        generate_mock.assert_not_awaited()
        # 没抢到锁也要正常关闭本次新建的 Redis 连接，不能泄漏。
        redis_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runs_and_releases_lock_when_acquired(self, monkeypatch):
        redis_client = _fake_redis(acquired=True)
        monkeypatch.setattr(summary_mod.aioredis, "from_url", lambda *a, **k: redis_client)
        generate_mock = AsyncMock()
        monkeypatch.setattr(summary_mod, "_generate_summary", generate_mock)

        await summary_mod.maybe_generate_summary("intake", "conv-1", window_size=16)

        generate_mock.assert_awaited_once_with("intake", "conv-1", window_size=16)
        redis_client.eval.assert_awaited_once()
        redis_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_releases_lock_even_if_generation_raises(self, monkeypatch):
        """生成过程中抛出意料之外的异常时，锁必须照样释放——不能只依赖 TTL
        到期兜底，否则同一会话要等到锁自然过期才能再次生成摘要。"""
        redis_client = _fake_redis(acquired=True)
        monkeypatch.setattr(summary_mod.aioredis, "from_url", lambda *a, **k: redis_client)
        monkeypatch.setattr(
            summary_mod, "_generate_summary", AsyncMock(side_effect=RuntimeError("boom"))
        )

        with pytest.raises(RuntimeError):
            await summary_mod.maybe_generate_summary("intake", "conv-1", window_size=16)

        redis_client.eval.assert_awaited_once()
        redis_client.aclose.assert_awaited_once()


# ── _generate_summary：窗口批量推进 ──────────────────────────────────────────

class TestSummaryWindowBatching:
    @pytest.mark.asyncio
    async def test_skips_when_backlog_has_not_filled_a_full_window(self, monkeypatch):
        """还没攒够一整个窗口的新老化消息时不应该调用摘要 LLM。"""
        monkeypatch.setattr(summary_mod, "_load_latest_seq", AsyncMock(return_value=20))
        monkeypatch.setattr(
            summary_mod.store,
            "load_summary",
            AsyncMock(return_value=SimpleNamespace(covered_through_seq=10, summary_json={})),
        )
        llm_mock = AsyncMock()
        monkeypatch.setattr(summary_mod, "_call_summary_llm", llm_mock)
        upsert_mock = AsyncMock()
        monkeypatch.setattr(summary_mod.store, "upsert_summary", upsert_mock)

        fake_db = AsyncMock()
        with patch("app.database.async_session_maker", return_value=_FakeAsyncSessionCm(fake_db)):
            # latest_seq(20) - covered_through_seq(10) = 10 < window_size(16)
            await summary_mod._generate_summary("intake", "conv-1", window_size=16)

        llm_mock.assert_not_awaited()
        upsert_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_advances_exactly_one_window_even_with_larger_backlog(self, monkeypatch):
        """服务中断导致积压了 3 个窗口的消息（latest_seq - covered = 48）时，
        单次调用也只推进一个窗口，不会一次性把积压全部追平——追平节奏见
        _generate_summary 里的注释。"""
        monkeypatch.setattr(summary_mod, "_load_latest_seq", AsyncMock(return_value=58))
        monkeypatch.setattr(
            summary_mod.store,
            "load_summary",
            AsyncMock(
                return_value=SimpleNamespace(covered_through_seq=10, summary_json={"confirmed_facts": []})
            ),
        )
        fake_messages = [SimpleNamespace(role="user", content="预算5万")]
        monkeypatch.setattr(summary_mod, "_load_segment", AsyncMock(return_value=fake_messages))
        monkeypatch.setattr(
            summary_mod, "_call_summary_llm", AsyncMock(return_value='{"confirmed_facts": ["预算5万"]}')
        )
        upsert_mock = AsyncMock()
        monkeypatch.setattr(summary_mod.store, "upsert_summary", upsert_mock)

        fake_db = AsyncMock()
        with patch("app.database.async_session_maker", return_value=_FakeAsyncSessionCm(fake_db)):
            await summary_mod._generate_summary("intake", "conv-1", window_size=16)

        upsert_mock.assert_awaited_once()
        kwargs = upsert_mock.call_args.kwargs
        assert kwargs["covered_through_seq"] == 26  # 10 + 16，不是 58
        assert kwargs["expected_covered_through_seq"] == 10

    @pytest.mark.asyncio
    async def test_first_summary_starts_from_zero(self, monkeypatch):
        """会话从未生成过摘要（existing=None）时，起点是 0，而不是报错或跳过。"""
        monkeypatch.setattr(summary_mod, "_load_latest_seq", AsyncMock(return_value=16))
        monkeypatch.setattr(summary_mod.store, "load_summary", AsyncMock(return_value=None))
        fake_messages = [SimpleNamespace(role="user", content="预算5万")]
        monkeypatch.setattr(summary_mod, "_load_segment", AsyncMock(return_value=fake_messages))
        monkeypatch.setattr(
            summary_mod, "_call_summary_llm", AsyncMock(return_value='{"confirmed_facts": ["预算5万"]}')
        )
        upsert_mock = AsyncMock()
        monkeypatch.setattr(summary_mod.store, "upsert_summary", upsert_mock)

        fake_db = AsyncMock()
        with patch("app.database.async_session_maker", return_value=_FakeAsyncSessionCm(fake_db)):
            await summary_mod._generate_summary("intake", "conv-1", window_size=16)

        kwargs = upsert_mock.call_args.kwargs
        assert kwargs["covered_through_seq"] == 16
        assert kwargs["expected_covered_through_seq"] == 0

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_advance_covered_through_seq(self, monkeypatch):
        """摘要 LLM 调用失败时必须保留旧摘要不动——不能推进 covered_through_seq
        却没有真正生成新内容，否则这段消息会被永久跳过、再也不会被摘要覆盖。"""
        monkeypatch.setattr(summary_mod, "_load_latest_seq", AsyncMock(return_value=16))
        monkeypatch.setattr(
            summary_mod.store,
            "load_summary",
            AsyncMock(return_value=SimpleNamespace(covered_through_seq=0, summary_json=None)),
        )
        fake_messages = [SimpleNamespace(role="user", content="预算5万")]
        monkeypatch.setattr(summary_mod, "_load_segment", AsyncMock(return_value=fake_messages))
        monkeypatch.setattr(
            summary_mod, "_call_summary_llm", AsyncMock(side_effect=RuntimeError("litellm timeout"))
        )
        upsert_mock = AsyncMock()
        monkeypatch.setattr(summary_mod.store, "upsert_summary", upsert_mock)

        fake_db = AsyncMock()
        with patch("app.database.async_session_maker", return_value=_FakeAsyncSessionCm(fake_db)):
            await summary_mod._generate_summary("intake", "conv-1", window_size=16)

        upsert_mock.assert_not_awaited()
