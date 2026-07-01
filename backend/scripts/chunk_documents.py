"""
文档切分 + 向量化入库脚本 (PRD §9.2)

用法:
    python scripts/chunk_documents.py --doc-id <uuid>       # 处理单个 document
    python scripts/chunk_documents.py --all                  # 处理所有 raw/parsed documents
    python scripts/chunk_documents.py --embed-only           # 只对 embedding IS NULL 的 chunks 补跑向量化

Chunk 策略 (PRD Table §9.2):
    charter          (招生章程 PDF)   400 tokens,  80 token overlap
    major_intro      (专业介绍)       300 tokens,  60 token overlap
    employment_report (就业报告)      500 tokens, 100 token overlap
    policy           (政策文件)       300 tokens,  50 token overlap
    default                           400 tokens,  80 token overlap
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
from typing import Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.engine.embedding import embed_pending_chunks, EMBEDDING_MODEL
from app.models.base import Base
from app.models.document import Chunk, Document

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Chunk 策略 ─────────────────────────────────────────────────────────────────

_CHUNK_PARAMS: dict[str, tuple[int, int]] = {
    "charter":           (400, 80),
    "major_intro":       (300, 60),
    "employment_report": (500, 100),
    "policy":            (300, 50),
}
_DEFAULT_CHUNK = (400, 80)


def _estimate_tokens(text: str) -> int:
    """Rough CJK-aware token estimate: ~1.5 chars per token for Chinese."""
    return max(1, len(text) // 2)


def _split_text(text: str, max_tokens: int, overlap_tokens: int) -> Iterator[str]:
    """
    Sliding-window split on sentence boundaries.
    Falls back to hard character-count split when no boundary found.
    """
    sentences = re.split(r"(?<=[。！？\n])", text)
    buf: list[str] = []
    buf_tokens = 0

    for sent in sentences:
        sent_tokens = _estimate_tokens(sent)
        if buf_tokens + sent_tokens > max_tokens and buf:
            yield "".join(buf).strip()
            # Keep overlap: drop sentences from front until below overlap budget
            while buf and buf_tokens - _estimate_tokens(buf[0]) >= buf_tokens - overlap_tokens:
                removed = buf.pop(0)
                buf_tokens -= _estimate_tokens(removed)
        buf.append(sent)
        buf_tokens += sent_tokens

    if buf:
        yield "".join(buf).strip()


def chunk_text(
    text: str,
    doc_type: str,
    doc_id: str,
    metadata: dict | None = None,
) -> list[dict]:
    """Return list of chunk dicts ready to insert into chunks table."""
    max_tok, overlap_tok = _CHUNK_PARAMS.get(doc_type, _DEFAULT_CHUNK)
    base_meta = metadata or {}

    chunks = []
    for idx, piece in enumerate(_split_text(text, max_tok, overlap_tok)):
        if not piece.strip():
            continue
        chunks.append({
            "id": str(uuid4()),
            "document_id": doc_id,
            "content": piece,
            "metadata_json": {**base_meta, "chunk_index": idx},
            "embedding": None,
            "embedding_model": None,
        })
    return chunks


# ── DB helpers ────────────────────────────────────────────────────────────────

def _ensure_asyncpg_url(url: str) -> str:
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


async def process_document(doc: Document, session: AsyncSession) -> int:
    """Chunk a single document and persist Chunk rows. Returns chunk count."""
    if not doc.title:
        logger.warning("Document %s has no content title, skipping", doc.id)
        return 0

    # Use title + type as synthetic text for demo; real pipeline would read file content
    text = f"{doc.title}\n\n（此处为文档正文占位，实际从文件解析获取）"
    meta = {
        "province": None,
        "university_id": None,
        "year": doc.year,
        "doc_type": doc.type,
        "authority_level": doc.authority_level,
    }

    chunks_data = chunk_text(text, doc.type, doc.id, meta)
    for cd in chunks_data:
        session.add(Chunk(**cd))

    doc.status = "parsed"
    await session.commit()
    logger.info("Document %s → %d chunks", doc.id, len(chunks_data))
    return len(chunks_data)


async def run(doc_id: str | None, all_docs: bool, embed_only: bool) -> None:
    db_url = _ensure_asyncpg_url(settings.database_url)
    engine = create_async_engine(db_url, echo=False)

    async with AsyncSession(engine) as session:
        if embed_only:
            n = await embed_pending_chunks(session)
            logger.info("Embedded %d chunks", n)
            return

        if doc_id:
            doc = await session.get(Document, doc_id)
            if doc is None:
                logger.error("Document %s not found", doc_id)
                return
            docs = [doc]
        elif all_docs:
            result = await session.execute(
                select(Document).where(Document.status.in_(["raw", "parsed"]))
            )
            docs = list(result.scalars().all())
        else:
            logger.error("Specify --doc-id, --all, or --embed-only")
            return

        total_chunks = 0
        for doc in docs:
            total_chunks += await process_document(doc, session)

        logger.info("Total chunks created: %d", total_chunks)

        # Immediately embed the new chunks
        logger.info("Starting embedding pass...")
        embedded = await embed_pending_chunks(session)
        logger.info("Embedded %d chunks", embedded)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chunk and embed documents")
    parser.add_argument("--doc-id", help="Process a single document by ID")
    parser.add_argument("--all", action="store_true", help="Process all raw/parsed documents")
    parser.add_argument("--embed-only", action="store_true", help="Only run embedding on pending chunks")
    args = parser.parse_args()

    asyncio.run(run(args.doc_id, args.all, args.embed_only))
