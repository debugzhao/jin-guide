"""
RAG 检索工具 (PRD §9.2, §10.4)

三个工具:
  vector_search        — pgvector cosine similarity, top-20
  search_admission_sql — 结构化数据精确检索 (AdmissionScore)
  rerank_evidence      — Cohere Rerank API, top-8, score<0.3 过滤
                         + 单 document_id 最多 3 chunks
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

import httpx
from langsmith import traceable
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.agent.circuit_breaker import get_circuit_breaker
from app.agent.tool_response import ToolResponse
from app.config import settings
from app.models.admission import AdmissionScore, University
from app.models.document import Chunk, Document

logger = logging.getLogger(__name__)

_breaker = get_circuit_breaker()

RERANK_MODEL = "rerank-multilingual-v3.0"
RERANK_SCORE_FLOOR = 0.3
RERANK_TOP_N = 8
VECTOR_TOP_K = 20
MAX_CHUNKS_PER_DOC = 3
_COHERE_RERANK_URL = "https://api.cohere.ai/v1/rerank"
# 只对"重试可能有用"的瞬时故障（超时/连接失败/429 限流/5xx）重试一次；401/403
# 鉴权失败和其他 4xx 客户端错误不重试——key 不对不会因为多试一次就突然对了，
# 白白浪费一次调用额度还多等一轮延迟。
_COHERE_MAX_ATTEMPTS = 2
_COHERE_RETRY_BACKOFF_SECONDS = 0.5
# Cohere 不可用（熔断/未配置/调用失败）时的降级门槛：pgvector 余弦相似度和 Cohere
# cross-encoder 相关性分数不是同一把尺子，这里的 0.55 不是"等价换算"，是从一次真实
# 案例（东华大学"学费"问题）里标定的经验值——命中学费的正确 chunk 相似度 0.66，
# 同一份章程里跑题的"志愿投档"段落 0.52，另一份专业介绍文档 0.48，都在这条线以下。
# 没有这道门槛，降级路径此前是"不管分数多低，硬凑够 top_n 个"，噪声会原样交给用户。
DEGRADED_SIMILARITY_FLOOR = 0.55


# ── 1. vector_search ──────────────────────────────────────────────────────────

def _process_vector_search_inputs(inputs: dict) -> dict:
    # db 是 AsyncSession，不可序列化也不该出现在 trace 里；query_vector 是 1024
    # 维浮点数组，记完整值对排查没帮助，只留维度
    safe = {k: v for k, v in inputs.items() if k != "db"}
    if safe.get("query_vector") is not None:
        safe["query_vector"] = f"<{len(safe['query_vector'])}-dim vector>"
    return safe


@traceable(run_type="tool", name="vector_search", process_inputs=_process_vector_search_inputs)
async def vector_search(
    query_vector: list[float],
    province: str | None = None,
    university_code: str | None = None,
    doc_type: str | None = None,
    top_k: int = VECTOR_TOP_K,
    db: AsyncSession = None,
) -> ToolResponse:
    """
    通过 pgvector HNSW 索引做余弦相似度检索。
    返回按 chunk_id 去重后的 top-k chunks。
    优雅降级：CircuitBreaker 保护，防止 pgvector 反复故障时持续打挂它。
    """
    if _breaker.is_open("pgvector"):
        return ToolResponse.partial(
            text="pgvector circuit breaker OPEN — vector search unavailable",
            data={"chunks": [], "degraded": True},
        )

    try:
        # 用余弦距离算子构造基础查询
        distance_expr = Chunk.embedding.cosine_distance(query_vector)
        query = (
            select(
                Chunk.id,
                Chunk.document_id,
                Chunk.content,
                Chunk.metadata_json,
                (1 - distance_expr).label("similarity"),
            )
            .where(Chunk.embedding.isnot(None))
            .order_by(distance_expr)
            .limit(top_k)
        )

        # 通过 metadata_json 附加的可选过滤条件
        if province:
            query = query.where(
                Chunk.metadata_json["province"].as_string() == province
            )
        if university_code:
            # 采集流水线写入 rag_chunks.metadata_json 用的键名是 university_code
            # （教育部院校代码，如"10335"），不是 university_id（内部 UUID）——
            # 之前这里错用 university_id 作为过滤键，导致按校过滤的向量检索
            # 一直静默返回 0 条结果（已用真实数据核实：731 条 rag_chunks 的
            # metadata_json 里只有 university_code 这个键，没有任何一条有
            # university_id）。
            query = query.where(
                Chunk.metadata_json["university_code"].as_string() == university_code
            )
        if doc_type:
            query = query.join(Document, Chunk.document_id == Document.id).where(
                Document.type == doc_type
            )

        rows = (await db.execute(query)).all()

        chunks = [
            {
                "chunk_id": r.id,
                "document_id": r.document_id,
                "content": r.content,
                "metadata": r.metadata_json or {},
                "similarity": round(float(r.similarity), 4),
            }
            for r in rows
        ]

        # 按 chunk_id 去重，保留相似度最高的一条（结果已按相似度排序）
        seen: set[str] = set()
        deduped = []
        for c in chunks:
            if c["chunk_id"] not in seen:
                seen.add(c["chunk_id"])
                deduped.append(c)

        _breaker.record_result("pgvector", ToolResponse.success("ok", {}))
        return ToolResponse.success(
            text=f"vector_search returned {len(deduped)} chunks",
            data={"chunks": deduped},
        )

    except Exception as exc:
        err = ToolResponse.error("VECTOR_SEARCH_FAILED", str(exc), {})
        _breaker.record_result("pgvector", err)
        logger.exception("vector_search failed")
        return err


# ── 2. search_admission_sql ───────────────────────────────────────────────────

def search_admission_sql(
    province: str,
    batch: str,
    subject_type: str,
    year: int | None = None,
    university_id: str | None = None,
    limit: int = 50,
    db: Session = None,
) -> ToolResponse:
    """
    从 AdmissionScore 表做结构化数据精确检索。
    返回按年份降序、最低位次升序排列的分数记录列表。
    """
    stmt = (
        select(
            AdmissionScore.id,
            AdmissionScore.university_id,
            AdmissionScore.year,
            AdmissionScore.province,
            AdmissionScore.batch,
            AdmissionScore.subject_type,
            AdmissionScore.major_category,
            AdmissionScore.min_score,
            AdmissionScore.min_rank,
            AdmissionScore.avg_score,
            AdmissionScore.avg_rank,
            University.name.label("university_name"),
            University.is_985,
            University.is_211,
        )
        .join(University, AdmissionScore.university_id == University.id)
        .where(
            AdmissionScore.province == province,
            AdmissionScore.batch == batch,
            AdmissionScore.subject_type == subject_type,
        )
        .order_by(AdmissionScore.year.desc(), AdmissionScore.min_rank.asc())
        .limit(limit)
    )

    if year is not None:
        stmt = stmt.where(AdmissionScore.year == year)
    if university_id is not None:
        stmt = stmt.where(AdmissionScore.university_id == university_id)

    try:
        rows = db.execute(stmt).all()
        records = [
            {
                "id": r.id,
                "university_id": r.university_id,
                "university_name": r.university_name,
                "year": r.year,
                "province": r.province,
                "batch": r.batch,
                "subject_type": r.subject_type,
                "major_category": r.major_category,
                "min_score": r.min_score,
                "min_rank": r.min_rank,
                "avg_score": r.avg_score,
                "avg_rank": r.avg_rank,
                "is_985": r.is_985,
                "is_211": r.is_211,
                "source_type": "sql_exact",
            }
            for r in rows
        ]
        return ToolResponse.success(
            text=f"search_admission_sql returned {len(records)} records",
            data={"records": records},
        )
    except Exception as exc:
        logger.exception("search_admission_sql failed")
        return ToolResponse.error("SQL_SEARCH_FAILED", str(exc), {})


def _degrade_to_vector_top_n(chunks: list[dict], top_n: int) -> list[dict]:
    """Cohere 不可用时的降级排序：按相似度过一遍 DEGRADED_SIMILARITY_FLOOR，
    并复用 MAX_CHUNKS_PER_DOC 限制单文档条数——不然低质量匹配会原样凑数返回。"""
    above_floor = [c for c in chunks if c.get("similarity", 0) >= DEGRADED_SIMILARITY_FLOOR]
    ranked = sorted(above_floor, key=lambda c: c.get("similarity", 0), reverse=True)

    doc_counts: dict[str, int] = defaultdict(int)
    filtered: list[dict] = []
    for c in ranked:
        doc_id = c.get("document_id", "")
        if doc_counts[doc_id] < MAX_CHUNKS_PER_DOC:
            doc_counts[doc_id] += 1
            filtered.append(c)
        if len(filtered) >= top_n:
            break
    return filtered


class CohereAuthError(Exception):
    """Cohere 返回 401/403——key 缺失/失效，重试没有意义，直接让调用方降级。"""


async def _call_cohere_rerank(query: str, documents: list[str]) -> list[dict]:
    """
    真正发起 Cohere Rerank API 调用，按错误类型分类处理：
    - 401/403：鉴权失败，记一条明确日志方便定位（2026-08-24 那次 .env 内联注释
      污染 COHERE_API_KEY 的 bug，排查耗时长的一部分原因就是这里当时只有一句
      笼统的 "RERANK_FAILED"，看不出到底是鉴权问题还是别的），不重试直接抛出。
    - 429/5xx/超时/连接失败：瞬时故障，重试一次（带短暂退避）后仍失败才抛出。
    - 其他 4xx（比如请求体格式错）：不重试，直接抛出。
    """
    last_exc: Exception | None = None
    for attempt in range(1, _COHERE_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    _COHERE_RERANK_URL,
                    headers={
                        "Authorization": f"Bearer {settings.cohere_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": RERANK_MODEL,
                        "query": query,
                        "documents": documents,
                        "top_n": len(documents),
                        "return_documents": False,
                    },
                )
            if resp.status_code in (401, 403):
                logger.error(
                    "Cohere rerank 鉴权失败（HTTP %s）——请检查 COHERE_API_KEY 是否正确配置",
                    resp.status_code,
                )
                raise CohereAuthError(f"Cohere rerank auth failed: HTTP {resp.status_code}")
            if resp.status_code == 429:
                logger.warning("Cohere rerank 触发限流（HTTP 429），第 %s/%s 次尝试", attempt, _COHERE_MAX_ATTEMPTS)
            resp.raise_for_status()
            return resp.json()["results"]

        except CohereAuthError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status < 500 and status != 429:
                # 其他 4xx（请求本身有问题）重试也不会成功
                raise
            last_exc = exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc

        if attempt < _COHERE_MAX_ATTEMPTS:
            await asyncio.sleep(_COHERE_RETRY_BACKOFF_SECONDS)

    assert last_exc is not None
    raise last_exc


# ── 3. rerank_evidence ────────────────────────────────────────────────────────

@traceable(run_type="tool", name="rerank_evidence")
async def rerank_evidence(
    query: str,
    chunks: list[dict],
    top_n: int = RERANK_TOP_N,
) -> ToolResponse:
    """
    用 Cohere Rerank API（rerank-multilingual-v3.0）对 chunks 重排序。
    过滤规则：score < 0.3 的丢弃；同一个 document_id 最多保留 3 个 chunk。
    熔断器 OPEN 或 API 调用失败时降级为向量相似度 top-8。
    """
    if not chunks:
        return ToolResponse.success("no chunks to rerank", {"chunks": []})

    if _breaker.is_open("cohere_rerank"):
        # 降级：按相似度分数取前 top_n 个（过 DEGRADED_SIMILARITY_FLOOR，见常量注释）
        degraded = _degrade_to_vector_top_n(chunks, top_n)
        return ToolResponse.partial(
            text="Cohere rerank circuit breaker OPEN — using vector top-N fallback",
            data={"chunks": degraded, "degraded": True},
        )

    if not settings.cohere_api_key:
        # 未配置 API key —— 优雅降级
        degraded = _degrade_to_vector_top_n(chunks, top_n)
        return ToolResponse.partial(
            text="Cohere API key not configured — using vector top-N fallback",
            data={"chunks": degraded, "degraded": True},
        )

    documents = [c.get("content", "") for c in chunks]

    try:
        results = await _call_cohere_rerank(query, documents)

        # 把 rerank 分数附加到原始 chunk 上
        scored = []
        for r in results:
            chunk = dict(chunks[r["index"]])
            chunk["rerank_score"] = r["relevance_score"]
            scored.append(chunk)

        # 过滤掉 score < 0.3 的结果
        scored = [c for c in scored if c["rerank_score"] >= RERANK_SCORE_FLOOR]

        # 限制每个 document_id 最多 3 个 chunk
        doc_counts: dict[str, int] = defaultdict(int)
        filtered: list[dict] = []
        for c in scored:
            doc_id = c.get("document_id", "")
            if doc_counts[doc_id] < MAX_CHUNKS_PER_DOC:
                doc_counts[doc_id] += 1
                filtered.append(c)
            if len(filtered) >= top_n:
                break

        _breaker.record_result("cohere_rerank", ToolResponse.success("ok", {}))
        return ToolResponse.success(
            text=f"rerank_evidence returned {len(filtered)} chunks after filtering",
            data={"chunks": filtered},
        )

    except Exception as exc:
        err = ToolResponse.error("RERANK_FAILED", str(exc), {})
        _breaker.record_result("cohere_rerank", err)
        logger.exception("rerank_evidence failed")
        # 降级为按向量相似度取 top_n
        degraded = _degrade_to_vector_top_n(chunks, top_n)
        return ToolResponse.partial(
            text=f"rerank failed ({exc!s}), using vector top-N fallback",
            data={"chunks": degraded, "degraded": True},
        )
