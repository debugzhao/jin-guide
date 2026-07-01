"""
RAG 检索工具 (PRD §9.2, §10.4)

三个工具:
  vector_search        — pgvector cosine similarity, top-20
  search_admission_sql — 结构化数据精确检索 (AdmissionScore)
  rerank_evidence      — Cohere Rerank API, top-8, score<0.3 过滤
                         + 单 document_id 最多 3 chunks
"""
from __future__ import annotations

import logging
from collections import defaultdict

import httpx
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


# ── 1. vector_search ──────────────────────────────────────────────────────────

async def vector_search(
    query_vector: list[float],
    province: str | None = None,
    university_id: str | None = None,
    doc_type: str | None = None,
    top_k: int = VECTOR_TOP_K,
    db: AsyncSession = None,
) -> ToolResponse:
    """
    Cosine similarity search via pgvector HNSW index.
    Returns top-k chunks deduped by chunk_id.
    Degrades gracefully: CircuitBreaker protects against repeated pgvector failures.
    """
    if _breaker.is_open("pgvector"):
        return ToolResponse.partial(
            text="pgvector circuit breaker OPEN — vector search unavailable",
            data={"chunks": [], "degraded": True},
        )

    try:
        # Build base query with cosine distance operator
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

        # Optional filters via metadata_json
        if province:
            query = query.where(
                Chunk.metadata_json["province"].as_string() == province
            )
        if university_id:
            query = query.where(
                Chunk.metadata_json["university_id"].as_string() == university_id
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

        # Dedup by chunk_id, keep highest similarity (already sorted)
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
    Structured data exact retrieval from AdmissionScore.
    Returns list of score records ordered by year desc, min_rank asc.
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


# ── 3. rerank_evidence ────────────────────────────────────────────────────────

async def rerank_evidence(
    query: str,
    chunks: list[dict],
    top_n: int = RERANK_TOP_N,
) -> ToolResponse:
    """
    Rerank chunks using Cohere Rerank API (rerank-multilingual-v3.0).
    Filters: score < 0.3 discarded; same document_id max 3 chunks.
    Degrades to vector top-8 if circuit breaker is OPEN or API fails.
    """
    if not chunks:
        return ToolResponse.success("no chunks to rerank", {"chunks": []})

    if _breaker.is_open("cohere_rerank"):
        # Degraded: return first top_n by similarity score
        degraded = sorted(chunks, key=lambda c: c.get("similarity", 0), reverse=True)[:top_n]
        return ToolResponse.partial(
            text="Cohere rerank circuit breaker OPEN — using vector top-N fallback",
            data={"chunks": degraded, "degraded": True},
        )

    if not settings.cohere_api_key:
        # No API key configured — graceful degradation
        degraded = sorted(chunks, key=lambda c: c.get("similarity", 0), reverse=True)[:top_n]
        return ToolResponse.partial(
            text="Cohere API key not configured — using vector top-N fallback",
            data={"chunks": degraded, "degraded": True},
        )

    documents = [c.get("content", "") for c in chunks]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.cohere.ai/v1/rerank",
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
            resp.raise_for_status()
        results = resp.json()["results"]

        # Attach rerank score to original chunks
        scored = []
        for r in results:
            chunk = dict(chunks[r["index"]])
            chunk["rerank_score"] = r["relevance_score"]
            scored.append(chunk)

        # Filter score < 0.3
        scored = [c for c in scored if c["rerank_score"] >= RERANK_SCORE_FLOOR]

        # Limit 3 chunks per document_id
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
        # Degrade to vector similarity top_n
        degraded = sorted(chunks, key=lambda c: c.get("similarity", 0), reverse=True)[:top_n]
        return ToolResponse.partial(
            text=f"rerank failed ({exc!s}), using vector top-N fallback",
            data={"chunks": degraded, "degraded": True},
        )
