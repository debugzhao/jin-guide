"""
RAG 检索层质量评测：跑 datasets/rag_golden_set.yaml 里的真实业务 case，
离线测 Context Recall@20 / 重排后 Top3 命中率 / MRR，对应
backend/docs/rag模块评测方案.md §3/§7 定义的指标。

只测检索 + 重排两层，绕开 Agent 编排和生成环节，避免被最终答案的措辞干扰。
因此不 mock db/embedding/rerank —— 需要真的连上 docker-compose 里的
postgres（已灌入生产数据）、litellm（embedding 代理）、真实 Cohere key，
跑起来慢且依赖外部服务，全部标记 rag_quality，日常跑单测用
`pytest -m "not rag_quality"` 跳过，需要看质量报告时单独跑：

    docker compose exec backend python -m pytest tests/eval/rag_layer/test_retrieval_quality.py -v -s
"""
from __future__ import annotations

import pathlib
import statistics

import pytest
import yaml

from app.database import async_session_maker
from app.engine.embedding import embed_text
from app.engine.retrieval import rerank_evidence, vector_search

pytestmark = pytest.mark.rag_quality

DATASET_PATH = pathlib.Path(__file__).parent / "datasets" / "rag_golden_set.yaml"
VECTOR_TOP_K = 20
# 与 document_search.py::search_school_documents 最终返回给用户的 top-N 保持一致，
# 这样"重排后进入 Top3"测的就是用户实际会看到的那个列表，而不是内部候选池。
RERANK_TOP_N = 3


def _load_cases() -> list[dict]:
    raw = yaml.safe_load(DATASET_PATH.read_text(encoding="utf-8"))
    return raw["cases"]


async def _run_one_query(case: dict, query: str) -> dict:
    """跑一条 query，返回它在向量召回 Top20 / 重排 Top3 里的命中详情。"""
    query_vector = await embed_text(query)
    async with async_session_maker() as db:
        vec_result = await vector_search(
            query_vector=query_vector,
            university_code=case["university_code"],
            top_k=VECTOR_TOP_K,
            db=db,
        )
    assert vec_result.is_usable, f"vector_search 不可用: {vec_result.text}"
    vec_chunks = vec_result.data["chunks"]
    standard_ids = set(case["standard_chunk_ids"])

    vec_rank = next(
        (i for i, c in enumerate(vec_chunks) if c["chunk_id"] in standard_ids), None
    )

    rerank_result = await rerank_evidence(query=query, chunks=vec_chunks, top_n=RERANK_TOP_N)
    assert rerank_result.is_usable, f"rerank_evidence 不可用: {rerank_result.text}"
    rerank_chunks = rerank_result.data["chunks"]
    rerank_rank = next(
        (i for i, c in enumerate(rerank_chunks) if c["chunk_id"] in standard_ids), None
    )

    return {
        "query": query,
        "vec_hit_top20": vec_rank is not None,
        "vec_rank": vec_rank,
        "rerank_hit_top3": rerank_rank is not None,
        "rerank_rank": rerank_rank,
        "reciprocal_rank": 1.0 / (rerank_rank + 1) if rerank_rank is not None else 0.0,
        "degraded": bool(vec_result.data.get("degraded") or rerank_result.data.get("degraded")),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["id"])
async def test_retrieval_quality_case(case: dict) -> None:
    variants = [case["query"], *case.get("query_variants", [])]
    results = [await _run_one_query(case, q) for q in variants]

    for r in results:
        assert not r["degraded"], f"熔断/降级路径命中，本次评测结果不可信: {r['query']}"

    recall_at_20 = sum(r["vec_hit_top20"] for r in results) / len(results)
    top3_hit_ratio = sum(r["rerank_hit_top3"] for r in results) / len(results)
    mrr = statistics.mean(r["reciprocal_rank"] for r in results)

    print(f"\n[{case['id']}] {case['university_name']} — {len(results)} 个 query 变体")
    for r in results:
        vec_mark = "✓" if r["vec_hit_top20"] else "✗"
        rerank_mark = "✓" if r["rerank_hit_top3"] else "✗"
        print(
            f"  vec_top20={vec_mark}(rank={r['vec_rank']})  "
            f"rerank_top3={rerank_mark}(rank={r['rerank_rank']})  "
            f"query={r['query']!r}"
        )
    print(
        f"  Context Recall@20 = {recall_at_20:.0%}   "
        f"Top3 命中率 = {top3_hit_ratio:.0%}   MRR = {mrr:.3f}"
    )

    assert recall_at_20 == 1.0, "必要 chunk 必须先进入向量召回 Top20，重排救不回向量层就漏掉的证据"
    assert top3_hit_ratio >= case["min_top3_hit_ratio"], (
        f"Top3 命中率 {top3_hit_ratio:.0%} 低于要求的 {case['min_top3_hit_ratio']:.0%}"
    )
    # case["query"]（第一个变体）是最标准的问法，要求重排后排第 1；
    # 其余变体只要求进 Top3（见上面 min_top3_hit_ratio），不强制第一名。
    assert results[0]["rerank_rank"] == 0, "标准问法重排后必须排名第 1"
