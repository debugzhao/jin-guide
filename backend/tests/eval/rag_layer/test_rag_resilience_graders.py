"""
弹性组件的确定性评测，对应 backend/docs/Agent评测体系调研.md 里两类指标：

  6. RAG 检索层的排序/过滤规则是否被正确执行  -> TestRerankFilteringRules
  10. 模拟超时/故障后是否正确降级              -> TestCircuitBreakerStateMachine +
                                                TestRetrievalDegradesGracefully

CircuitBreaker.is_open()/record_result() 本身是纯状态机，不需要真的等待
recovery_timeout——通过 monkeypatch time.monotonic 模拟时间流逝。
vector_search/rerank_evidence 用的是全局单例（get_circuit_breaker()），
所以涉及它们的用例都要在 fixture 里显式 reset，避免状态漏到其他测试文件。
"""
from __future__ import annotations

import httpx
import pytest

from app.agent.circuit_breaker import BreakerState, CircuitBreaker, get_circuit_breaker
from app.agent.tool_response import ToolResponse


def _ok() -> ToolResponse:
    return ToolResponse.success("ok", {})


def _fail() -> ToolResponse:
    return ToolResponse.error("BOOM", "simulated failure", {})


# ── 10a. CircuitBreaker 状态机本身 ───────────────────────────────────────────────

class TestCircuitBreakerStateMachine:
    """全部用独立实例，不碰全局单例，纯测状态转换逻辑。"""

    def test_starts_closed_and_allows_calls(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert breaker.is_open("svc") is False
        assert breaker.get_state("svc") == BreakerState.CLOSED

    def test_two_consecutive_failures_stay_below_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        breaker.record_result("svc", _fail())
        breaker.record_result("svc", _fail())
        assert breaker.is_open("svc") is False
        assert breaker.get_state("svc") == BreakerState.CLOSED

    def test_third_consecutive_failure_opens_the_breaker(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            breaker.record_result("svc", _fail())
        assert breaker.is_open("svc") is True
        assert breaker.get_state("svc") == BreakerState.OPEN

    def test_success_in_between_resets_failure_count(self):
        """2 次失败 + 1 次成功 + 2 次失败不应该触发熔断——失败必须是连续的。"""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        breaker.record_result("svc", _fail())
        breaker.record_result("svc", _fail())
        breaker.record_result("svc", _ok())
        breaker.record_result("svc", _fail())
        breaker.record_result("svc", _fail())

        assert breaker.is_open("svc") is False

    def test_partial_status_counts_as_success(self):
        """PARTIAL 是“降级但可用”，不应该被当成失败继续累加熔断计数。"""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        breaker.record_result("svc", _fail())
        breaker.record_result("svc", _fail())
        breaker.record_result("svc", ToolResponse.partial("degraded", {}))
        breaker.record_result("svc", _fail())
        breaker.record_result("svc", _fail())

        assert breaker.is_open("svc") is False

    def test_open_breaker_blocks_calls_until_recovery_timeout_elapses(self, monkeypatch):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=300)
        clock = {"now": 1000.0}
        monkeypatch.setattr(
            "app.agent.circuit_breaker.time.monotonic", lambda: clock["now"]
        )

        for _ in range(3):
            breaker.record_result("svc", _fail())
        assert breaker.is_open("svc") is True  # 刚熔断，立刻查询仍然是拒绝

        clock["now"] += 299  # 还没到 300 秒冷却时间
        assert breaker.is_open("svc") is True

    def test_transitions_to_half_open_after_recovery_timeout(self, monkeypatch):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=300)
        clock = {"now": 1000.0}
        monkeypatch.setattr(
            "app.agent.circuit_breaker.time.monotonic", lambda: clock["now"]
        )

        for _ in range(3):
            breaker.record_result("svc", _fail())

        clock["now"] += 300  # 冷却期已过
        assert breaker.is_open("svc") is False  # 允许一次试探
        assert breaker.get_state("svc") == BreakerState.HALF_OPEN

    def test_half_open_trial_failure_reopens_the_breaker(self, monkeypatch):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=300)
        clock = {"now": 1000.0}
        monkeypatch.setattr(
            "app.agent.circuit_breaker.time.monotonic", lambda: clock["now"]
        )

        for _ in range(3):
            breaker.record_result("svc", _fail())
        clock["now"] += 300
        breaker.is_open("svc")  # 触发转入 HALF_OPEN

        breaker.record_result("svc", _fail())  # 试探失败

        assert breaker.is_open("svc") is True
        assert breaker.get_state("svc") == BreakerState.OPEN

    def test_half_open_trial_success_closes_the_breaker(self, monkeypatch):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=300)
        clock = {"now": 1000.0}
        monkeypatch.setattr(
            "app.agent.circuit_breaker.time.monotonic", lambda: clock["now"]
        )

        for _ in range(3):
            breaker.record_result("svc", _fail())
        clock["now"] += 300
        breaker.is_open("svc")  # 触发转入 HALF_OPEN

        breaker.record_result("svc", _ok())  # 试探成功

        assert breaker.is_open("svc") is False
        assert breaker.get_state("svc") == BreakerState.CLOSED

    def test_reset_clears_all_recorded_state(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            breaker.record_result("svc", _fail())
        assert breaker.is_open("svc") is True

        breaker.reset("svc")

        assert breaker.get_state("svc") == BreakerState.CLOSED
        assert breaker.is_open("svc") is False


# ── 10b. 真实工具接入全局熔断器后的降级路径 ───────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_global_breaker():
    """vector_search/rerank_evidence 绑定的是进程内全局单例，测试前后都要重置，
    避免这个文件的用例互相污染、也避免污染其他测试文件里同样用到全局熔断器的用例。"""
    breaker = get_circuit_breaker()
    breaker.reset("pgvector")
    breaker.reset("cohere_rerank")
    yield
    breaker.reset("pgvector")
    breaker.reset("cohere_rerank")


class TestRetrievalDegradesGracefully:
    @pytest.mark.asyncio
    async def test_vector_search_short_circuits_without_touching_db_when_breaker_open(self):
        from app.engine.retrieval import vector_search

        breaker = get_circuit_breaker()
        for _ in range(3):
            breaker.record_result("pgvector", _fail())

        # db=None：如果代码没有在熔断时提前 return，这里会因为对 None 调用 db.execute 而抛异常
        result = await vector_search(query_vector=[0.1, 0.2], db=None)

        assert result.is_partial
        assert result.data["degraded"] is True
        assert result.data["chunks"] == []

    @pytest.mark.asyncio
    async def test_rerank_evidence_degrades_to_similarity_ranking_when_breaker_open(self):
        from app.engine.retrieval import rerank_evidence

        breaker = get_circuit_breaker()
        for _ in range(3):
            breaker.record_result("cohere_rerank", _fail())

        chunks = [
            {"content": "较低相似度", "similarity": 0.6, "document_id": "d1"},
            {"content": "高相似度", "similarity": 0.9, "document_id": "d2"},
        ]
        result = await rerank_evidence(query="随便", chunks=chunks, top_n=8)

        assert result.is_partial
        assert result.data["degraded"] is True
        assert [c["content"] for c in result.data["chunks"]] == ["高相似度", "较低相似度"]

    @pytest.mark.asyncio
    async def test_rerank_evidence_degraded_fallback_still_filters_low_similarity_noise(self):
        """真实 Cohere 精排不可用时，降级路径此前是"不管分数多低，硬凑够 top_n 个"——
        2026-08-24 东华大学"学费"问题里，跑题的"专业介绍"片段（相似度 0.48）就是这样
        原样混进了回答。DEGRADED_SIMILARITY_FLOOR 应该把这类低质量匹配挡在外面，
        不能因为 Cohere 挂了就把及格线一起放弃。"""
        from app.engine.retrieval import rerank_evidence

        breaker = get_circuit_breaker()
        for _ in range(3):
            breaker.record_result("cohere_rerank", _fail())

        chunks = [
            {"content": "低相似度噪声", "similarity": 0.48, "document_id": "d1"},
            {"content": "高相似度正确答案", "similarity": 0.66, "document_id": "d2"},
        ]
        result = await rerank_evidence(query="学费标准", chunks=chunks, top_n=8)

        assert result.is_partial
        assert [c["content"] for c in result.data["chunks"]] == ["高相似度正确答案"]

    @pytest.mark.asyncio
    async def test_rerank_evidence_degrades_when_cohere_api_key_missing(self, monkeypatch):
        from app.engine import retrieval as module

        monkeypatch.setattr(module.settings, "cohere_api_key", "")
        chunks = [{"content": "唯一片段", "similarity": 0.9, "document_id": "d1"}]

        result = await module.rerank_evidence(query="随便", chunks=chunks)

        assert result.is_partial
        assert result.data["degraded"] is True
        assert result.data["chunks"] == chunks

    @pytest.mark.asyncio
    async def test_rerank_evidence_short_circuits_on_empty_chunks(self):
        from app.engine.retrieval import rerank_evidence

        result = await rerank_evidence(query="随便", chunks=[])

        assert result.is_success
        assert result.data["chunks"] == []


# ── 6. RAG 重排序的确定性过滤规则 ────────────────────────────────────────────────

class _FakeRerankResponse:
    def __init__(self, results: list[dict]) -> None:
        self._results = results
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"results": self._results}


class _FakeRerankClient:
    def __init__(self, results: list[dict]) -> None:
        self._results = results

    def __call__(self, *args, **kwargs) -> "_FakeRerankClient":
        return self

    async def __aenter__(self) -> "_FakeRerankClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, *args, **kwargs) -> _FakeRerankResponse:
        return _FakeRerankResponse(self._results)


class TestRerankFilteringRules:
    """
    真正命中 Cohere 分支后的两条确定性规则——评测体系文档里「知识检索层」表格中的
    “排序质量”“检索精确率”，落到代码上就是这两条硬规则：
      - rerank_score < RERANK_SCORE_FLOOR(0.3) 的候选必须被丢弃
      - 同一个 document_id 最多保留 MAX_CHUNKS_PER_DOC(3) 个 chunk
    这里用一个假的 httpx 客户端固定 Cohere 的返回顺序和分数，直接验证过滤后的结果。
    """

    @pytest.mark.asyncio
    async def test_score_floor_and_per_document_cap_are_enforced(self, monkeypatch):
        from app.engine import retrieval as module

        monkeypatch.setattr(module.settings, "cohere_api_key", "fake-key-for-test")

        chunks = [
            {"content": "doc1-c0", "document_id": "doc-1", "similarity": 0.5},  # idx 0
            {"content": "doc1-c1", "document_id": "doc-1", "similarity": 0.5},  # idx 1
            {"content": "doc1-c2", "document_id": "doc-1", "similarity": 0.5},  # idx 2
            {"content": "doc1-c3", "document_id": "doc-1", "similarity": 0.5},  # idx 3 (应被每文档上限挡掉)
            {"content": "doc2-c4", "document_id": "doc-2", "similarity": 0.5},  # idx 4
            {"content": "doc2-c5", "document_id": "doc-2", "similarity": 0.5},  # idx 5 (应被分数下限挡掉)
        ]
        # 按相关性降序排列，和 Cohere 真实返回顺序一致
        cohere_results = [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.90},
            {"index": 4, "relevance_score": 0.85},
            {"index": 2, "relevance_score": 0.80},  # doc-1 的第 3 个，命中上限边界，应保留
            {"index": 3, "relevance_score": 0.75},  # doc-1 的第 4 个，超过上限，应丢弃
            {"index": 5, "relevance_score": 0.10},  # 低于 0.3 下限，应丢弃
        ]
        monkeypatch.setattr(
            module.httpx, "AsyncClient", _FakeRerankClient(cohere_results)
        )

        result = await module.rerank_evidence(query="随便", chunks=chunks, top_n=8)

        assert result.is_success
        kept = [c["content"] for c in result.data["chunks"]]
        assert kept == ["doc1-c0", "doc1-c1", "doc2-c4", "doc1-c2"]
        assert "doc1-c3" not in kept, "同一文档超过 3 个 chunk 的部分必须被丢弃"
        assert "doc2-c5" not in kept, "分数低于 0.3 的候选必须被丢弃"

    @pytest.mark.asyncio
    async def test_top_n_truncates_after_filtering(self, monkeypatch):
        from app.engine import retrieval as module

        monkeypatch.setattr(module.settings, "cohere_api_key", "fake-key-for-test")

        chunks = [{"content": f"c{i}", "document_id": f"doc-{i}", "similarity": 0.5} for i in range(5)]
        cohere_results = [{"index": i, "relevance_score": 0.9 - i * 0.05} for i in range(5)]
        monkeypatch.setattr(
            module.httpx, "AsyncClient", _FakeRerankClient(cohere_results)
        )

        result = await module.rerank_evidence(query="随便", chunks=chunks, top_n=2)

        assert len(result.data["chunks"]) == 2
        assert [c["content"] for c in result.data["chunks"]] == ["c0", "c1"]


# ── 11. Cohere 调用的错误分类与重试 ───────────────────────────────────────────────

class _FakeStatusResponse:
    """按指定 status_code 模拟一次 httpx 响应；>=400 时 raise_for_status() 真的抛
    httpx.HTTPStatusError，行为和真实 httpx.Response 一致。"""

    def __init__(self, status_code: int, results: list[dict] | None = None) -> None:
        self.status_code = status_code
        self._results = results or []

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.cohere.ai/v1/rerank")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=request, response=response)

    def json(self) -> dict:
        return {"results": self._results}


class _SequencedFakeClient:
    """每次 post() 按顺序消费一个预设的响应/异常，用于验证重试次数和顺序。"""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def __call__(self, *args, **kwargs) -> "_SequencedFakeClient":
        return self

    async def __aenter__(self) -> "_SequencedFakeClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, *args, **kwargs):
        self.call_count += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TestCohereErrorHandlingAndRetry:
    """
    2026-08-25 加固：之前任何 Cohere 调用失败都被同一个 except Exception 兜住，
    日志里看不出是鉴权失败还是网络抖动——这次排查 .env 内联注释污染 COHERE_API_KEY
    的 bug 时吃了这个亏。现在 401/403 单独识别并立刻放弃（重试不会让坏 key 变好），
    429/5xx/超时这类瞬时故障重试一次。
    """

    @pytest.mark.asyncio
    async def test_auth_failure_does_not_retry_and_degrades_immediately(self, monkeypatch):
        from app.engine import retrieval as module

        monkeypatch.setattr(module.settings, "cohere_api_key", "bad-key")
        client = _SequencedFakeClient([_FakeStatusResponse(401)])
        monkeypatch.setattr(module.httpx, "AsyncClient", client)

        chunks = [{"content": "c0", "document_id": "doc-0", "similarity": 0.9}]
        result = await module.rerank_evidence(query="随便", chunks=chunks, top_n=8)

        assert client.call_count == 1, "401 鉴权失败不应该重试"
        assert result.is_partial
        assert result.data["degraded"] is True

    @pytest.mark.asyncio
    async def test_rate_limit_retries_once_then_succeeds(self, monkeypatch):
        from app.engine import retrieval as module

        monkeypatch.setattr(module.settings, "cohere_api_key", "fake-key-for-test")
        monkeypatch.setattr(module, "_COHERE_RETRY_BACKOFF_SECONDS", 0)
        client = _SequencedFakeClient([
            _FakeStatusResponse(429),
            _FakeStatusResponse(200, [{"index": 0, "relevance_score": 0.9}]),
        ])
        monkeypatch.setattr(module.httpx, "AsyncClient", client)

        chunks = [{"content": "c0", "document_id": "doc-0", "similarity": 0.9}]
        result = await module.rerank_evidence(query="随便", chunks=chunks, top_n=8)

        assert client.call_count == 2, "429 限流应该重试一次"
        assert result.is_success
        assert result.data["chunks"][0]["rerank_score"] == 0.9

    @pytest.mark.asyncio
    async def test_persistent_timeout_exhausts_retries_then_degrades(self, monkeypatch):
        from app.engine import retrieval as module

        monkeypatch.setattr(module.settings, "cohere_api_key", "fake-key-for-test")
        monkeypatch.setattr(module, "_COHERE_RETRY_BACKOFF_SECONDS", 0)
        timeout_exc = httpx.TimeoutException("timed out")
        client = _SequencedFakeClient([timeout_exc, timeout_exc])
        monkeypatch.setattr(module.httpx, "AsyncClient", client)

        chunks = [{"content": "c0", "document_id": "doc-0", "similarity": 0.9}]
        result = await module.rerank_evidence(query="随便", chunks=chunks, top_n=8)

        assert client.call_count == 2, "超时应该重试一次，两次都超时后放弃"
        assert result.is_partial
        assert result.data["degraded"] is True

    @pytest.mark.asyncio
    async def test_other_client_error_does_not_retry(self, monkeypatch):
        """比如请求体格式错这类 4xx（非 401/403/429），重试不会成功，不该浪费一次调用。"""
        from app.engine import retrieval as module

        monkeypatch.setattr(module.settings, "cohere_api_key", "fake-key-for-test")
        client = _SequencedFakeClient([_FakeStatusResponse(400)])
        monkeypatch.setattr(module.httpx, "AsyncClient", client)

        chunks = [{"content": "c0", "document_id": "doc-0", "similarity": 0.9}]
        result = await module.rerank_evidence(query="随便", chunks=chunks, top_n=8)

        assert client.call_count == 1
        assert result.is_partial
        assert result.data["degraded"] is True
