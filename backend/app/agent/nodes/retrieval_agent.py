"""
Retrieval Agent node (M2): SQL structured search + vector search → rerank → evidence pack.
Runs in parallel with policy_rule_agent after data_resolver.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.agent.state import VolunteerPlanState
from app.config import settings

logger = logging.getLogger(__name__)


async def _push_sse(run_id: str, event: str, data: dict) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.xadd(
            f"sse:{run_id}",
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
        )
        await redis_client.expire(f"sse:{run_id}", 3600)
    finally:
        await redis_client.aclose()


def _sql_search_sync(province: str, batch: str, subject_type: str) -> list[dict]:
    from app.database import SyncSessionLocal
    from app.engine.retrieval import search_admission_sql

    with SyncSessionLocal() as db:
        result = search_admission_sql(
            province=province,
            batch=batch,
            subject_type=subject_type,
            year=None,
            limit=200,
            db=db,
        )
    if result.status == "SUCCESS":
        return result.data.get("records", [])
    return []


async def retrieval_agent(state: VolunteerPlanState) -> dict:
    run_id = state["run_id"]
    profile = state.get("profile") or {}

    await _push_sse(run_id, "node_started", {"node": "retrieval_agent", "message": "正在检索招生数据"})

    province = profile.get("province", "")
    batch = profile.get("batch", "本科批")
    subject_type = profile.get("subject_type", "physics")

    evidence_list: list[dict] = []
    retrieved_at = datetime.now(UTC).isoformat()

    # ── 1. SQL search (sync, run in thread) ──────────────────────────────────
    sql_records = await asyncio.to_thread(_sql_search_sync, province, batch, subject_type)

    seen_univ: set[str] = set()
    for rec in sql_records:
        uid = rec.get("university_id", "")
        if uid not in seen_univ:
            seen_univ.add(uid)
            evidence_list.append({
                "source_id": f"sql_{uid}_{rec.get('year', '')}",
                "source_type": "admission_score",
                "title": f"{rec.get('university_name', '')}录取分数线（{rec.get('year', '')}年）",
                "authority_level": "official",
                "year": rec.get("year"),
                "province": province,
                "batch": batch,
                "dataset_version": state.get("dataset_version", ""),
                "retrieved_at": retrieved_at,
                "fields": ["min_score", "min_rank", "enrollment_count"],
                "quote": (
                    f"{rec.get('university_name', '')} {rec.get('year', '')}年"
                    f"最低录取位次 {rec.get('min_rank', 'N/A')}"
                ),
                "data": rec,
            })

    if evidence_list:
        await _push_sse(run_id, "evidence_found", {
            "source_count": len(evidence_list),
            "source_type": "admission_score",
            "message": f"检索到 {len(evidence_list)} 所院校的历年录取数据",
        })

    # ── 2. Vector search + rerank (graceful degrade) ─────────────────────────
    try:
        from app.engine.embedding import embed_text

        query_text = f"{province} {batch} 招生计划 录取分数线 选科要求"
        query_vector = await asyncio.to_thread(embed_text, query_text)

        from app.database import async_session_maker
        from app.engine.retrieval import rerank_evidence, vector_search

        async with async_session_maker() as db:
            v_result = await vector_search(
                query_vector=query_vector,
                province=province,
                university_id=None,
                doc_type=None,
                top_k=20,
                db=db,
            )

        if v_result.status in ("SUCCESS", "PARTIAL"):
            chunks = v_result.data.get("chunks", [])
            reranked = await rerank_evidence(query_text, chunks)
            for chunk in reranked.data.get("chunks", []):
                evidence_list.append({
                    "source_id": chunk.get("document_id", ""),
                    "source_type": "document",
                    "title": "相关政策/章程片段",
                    "content": chunk.get("content", "")[:300],
                    "retrieved_at": retrieved_at,
                    "relevance_score": chunk.get("rerank_score") or chunk.get("similarity", 0),
                    "dataset_version": state.get("dataset_version", ""),
                })
    except Exception as exc:
        logger.warning("Vector search skipped in retrieval_agent: %s", exc)

    await _push_sse(run_id, "node_completed", {
        "node": "retrieval_agent",
        "evidence_count": len(evidence_list),
        "message": f"检索完成，共 {len(evidence_list)} 条证据",
    })

    return {
        "evidence_list": evidence_list,
        "retrieval_complete": True,
    }
