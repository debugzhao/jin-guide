"""
Embedding 流水线：通过 LiteLLM Gateway 批量将文本向量化。
模型：text-embedding-3-small 是 LiteLLM 虚拟模型名，实际后端是 DashScope qwen3.7-text-embedding（1024 维，
2026-08-22 从 Moonshot moonshot-v1-emb-small 切换，原因见 backend/docs/04_rag_pipeline.md §9）
所有 embedding 调用都必须经过 LiteLLM proxy —— 禁止直连 OpenAI。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Chunk

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1024
# DashScope qwen3.7-text-embedding 硬性限制单次请求最多20条文本（超出返回
# InternalError.Algo.InvalidParameter: batch size...should not be larger than 20），
# 切换供应商前 Moonshot 用的是100，没跟着改会导致chunk数一超过20整批请求失败。
_BATCH_SIZE = 20

logger = logging.getLogger(__name__)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    通过 LiteLLM proxy 对一批文本做向量化。
    返回的向量顺序与输入顺序一致。
    失败时抛出 httpx.HTTPError —— 重试/熔断由调用方处理。
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.litellm_base_url}/embeddings",
            headers={"Authorization": f"Bearer {settings.litellm_master_key}"},
            json={"model": EMBEDDING_MODEL, "input": texts},
        )
        resp.raise_for_status()
    data = resp.json()["data"]
    return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]


async def embed_text(text: str) -> list[float]:
    """对单条文本做向量化。"""
    results = await embed_batch([text])
    return results[0]


async def embed_pending_chunks(
    db: AsyncSession,
    batch_size: int = _BATCH_SIZE,
) -> int:
    """
    找出所有 embedding IS NULL 的 Chunk 记录，分批向量化后写回数据库。

    返回处理过的 chunk 总数。
    """
    result = await db.execute(
        select(Chunk).where(Chunk.embedding.is_(None)).order_by(Chunk.created_at)
    )
    pending: list[Chunk] = list(result.scalars().all())

    if not pending:
        logger.info("No pending chunks to embed.")
        return 0

    processed = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        texts = [c.content for c in batch]
        try:
            vectors = await embed_batch(texts)
            for chunk, vec in zip(batch, vectors):
                chunk.embedding = vec
                chunk.embedding_model = EMBEDDING_MODEL
            await db.flush()
            processed += len(batch)
            logger.info("Embedded %d/%d chunks", processed, len(pending))
        except Exception:
            logger.exception("Embedding batch %d failed, skipping", i // batch_size)

    await db.commit()
    return processed
