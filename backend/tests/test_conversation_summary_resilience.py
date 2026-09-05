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


# ── _call_summary_llm / _stream_summary_once：输出预算被 reasoning 吃满 ──────

class _FakeStreamResponse:
    """httpx 流式响应的最小替身，按行喂出预置的 SSE 文本。"""

    def __init__(self, lines: list[str]):
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    """替换 httpx.AsyncClient：记录每次请求的 JSON body，返回预置的 SSE 行。"""

    def __init__(self, responses: list[list[str]], captured: list[dict]):
        self._responses = responses
        self._captured = captured

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def stream(self, _method, _url, *, headers=None, json=None):
        self._captured.append(json)
        return _FakeStreamCm(self._responses[len(self._captured) - 1])


class _FakeStreamCm:
    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self):
        return _FakeStreamResponse(self._lines)

    async def __aexit__(self, *exc_info):
        return False


def _sse(content: str | None = None, *, finish_reason: str | None = None) -> str:
    delta = {"content": content} if content is not None else {}
    choice: dict = {"delta": delta}
    if finish_reason:
        choice["finish_reason"] = finish_reason
    return "data: " + __import__("json").dumps({"choices": [choice]}, ensure_ascii=False)


# 开了 stream_options.include_usage 之后真实响应最后会多一个 choices 为空的 chunk，
# 解析时不能因为它抛 IndexError 而丢掉已经攒好的正文。
_USAGE_CHUNK = 'data: {"choices": [], "usage": {"completion_tokens": 3000, "reasoning_tokens": 2999}}'


class TestSummaryOutputTruncation:
    @pytest.fixture(autouse=True)
    def _no_audit_writes(self, monkeypatch):
        """track_prompt_invocation 会写审计表，这里只测 HTTP 与重试决策。"""
        monkeypatch.setattr(summary_mod, "_SYSTEM_PROMPT", "sys")
        monkeypatch.setattr(
            "app.prompts.tracing._persist_trace", AsyncMock(return_value=None)
        )

    @pytest.mark.asyncio
    async def test_extracts_finish_reason_and_survives_usage_chunk(self, monkeypatch):
        lines = [_sse("{"), _sse('"a": 1}', finish_reason="stop"), _USAGE_CHUNK, "data: [DONE]"]
        client = _FakeAsyncClient([lines], captured=[])
        monkeypatch.setattr(summary_mod.httpx, "AsyncClient", client)

        content, finish_reason = await summary_mod._stream_summary_once(
            "u", parent_kind="intake", parent_id="conv-1"
        )

        assert content == '{"a": 1}'
        assert finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_no_retry_when_finished_normally(self, monkeypatch):
        captured: list[dict] = []
        lines = [_sse('{"confirmed_facts": []}', finish_reason="stop"), "data: [DONE]"]
        monkeypatch.setattr(
            summary_mod.httpx, "AsyncClient", _FakeAsyncClient([lines], captured)
        )

        content = await summary_mod._call_summary_llm("u", parent_kind="intake", parent_id="c1")

        assert content == '{"confirmed_facts": []}'
        assert len(captured) == 1, "正常结束不应该重试"

    @pytest.mark.asyncio
    async def test_retries_with_thinking_disabled_when_truncated_with_empty_content(
        self, monkeypatch
    ):
        """复现线上根因：reasoning 吃满 max_tokens，正文为空、finish_reason=length。"""
        captured: list[dict] = []
        first = [_sse(finish_reason="length"), _USAGE_CHUNK, "data: [DONE]"]
        second = [_sse('{"confirmed_facts": ["预算4.8万/年"]}', finish_reason="stop"), "data: [DONE]"]
        monkeypatch.setattr(
            summary_mod.httpx, "AsyncClient", _FakeAsyncClient([first, second], captured)
        )

        content = await summary_mod._call_summary_llm("u", parent_kind="intake", parent_id="c1")

        assert content == '{"confirmed_facts": ["预算4.8万/年"]}'
        assert len(captured) == 2, "被截断必须重试一次"
        base_max_tokens = summary_mod._PROMPT.model.max_tokens
        assert captured[0]["max_tokens"] == base_max_tokens
        assert "thinking" not in captured[0], "首次调用不改思考模式"
        assert captured[1]["max_tokens"] == base_max_tokens * 2, "重试要翻倍预算"
        assert captured[1]["thinking"] == {"type": "disabled"}, "重试要关掉思考模式"

    @pytest.mark.asyncio
    async def test_retries_when_truncated_even_if_partial_content(self, monkeypatch):
        """正文被截断留下残缺 JSON 时同样注定解析失败，也必须重试。"""
        captured: list[dict] = []
        first = [_sse('{"confirmed_facts": ["预'), _sse(finish_reason="length"), "data: [DONE]"]
        second = [_sse('{"confirmed_facts": []}', finish_reason="stop"), "data: [DONE]"]
        monkeypatch.setattr(
            summary_mod.httpx, "AsyncClient", _FakeAsyncClient([first, second], captured)
        )

        content = await summary_mod._call_summary_llm("u", parent_kind="intake", parent_id="c1")

        assert content == '{"confirmed_facts": []}'
        assert len(captured) == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_single_retry(self, monkeypatch):
        """重试后仍被截断时只记日志、不再重试，避免后台任务反复烧 token。"""
        captured: list[dict] = []
        truncated = [_sse(finish_reason="length"), "data: [DONE]"]
        monkeypatch.setattr(
            summary_mod.httpx,
            "AsyncClient",
            _FakeAsyncClient([truncated, list(truncated)], captured),
        )

        content = await summary_mod._call_summary_llm("u", parent_kind="intake", parent_id="c1")

        assert content == ""
        assert len(captured) == 2, "最多只重试一次"
