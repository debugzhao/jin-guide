"""
Embedding pipeline: batch vectorize text via LiteLLM Gateway.
Model: text-embedding-3-small (1536 dims, per PRD §9.2)
All embeddings go through the LiteLLM proxy — never call OpenAI directly.
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
EMBEDDING_DIMS = 1536
_BATCH_SIZE = 100

logger = logging.getLogger(__name__)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts via LiteLLM proxy.
    Returns vectors in the same order as input.
    Raises httpx.HTTPError on failure — caller handles retry/circuit-breaker.
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
    """Embed a single text string."""
    results = await embed_batch([text])
    return results[0]


async def embed_pending_chunks(
    db: AsyncSession,
    batch_size: int = _BATCH_SIZE,
) -> int:
    """
    Find all Chunk rows where embedding IS NULL, vectorize them in batches,
    and write the vectors back to the database.

    Returns total number of chunks processed.
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
