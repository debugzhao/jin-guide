"""
用新版 chunking 逻辑（导航噪声过滤 + 上下文保留关键词过滤 + 分级预算/overlap）
对已发布的 rag_documents 重新切分、重新入库、重新向量化。

背景：`data_pipeline/parsers/document.py::chunk_document` 是真正生产生效的切分函数，
但历史实现是"统一 1200 字符贪心拼接、无 overlap"，实测暴露三个问题（见
`backend/docs/rag模块核心问题.md` §2.5）：条款/列表在 chunk 边界被截断、
关键词过滤把不含关键词的条款整体丢弃、导航菜单文字污染 chunk。三个问题都已在
`split_into_chunks` 里修复，本脚本负责把修复后的逻辑回灌到已经入库的文档——
文档原始文件已经落盘（`rag_documents.raw_storage_path`），不需要重新抓取网络。

用法:
    python scripts/rechunk_documents.py --dry-run          # 只打印对比统计，不写库
    python scripts/rechunk_documents.py --doc-id <uuid>    # 只重切一个 document
    python scripts/rechunk_documents.py --all              # 重切所有 charter/policy/major_intro/transfer_policy
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.engine.embedding import embed_pending_chunks
from app.models.document import Chunk, Document
from data_pipeline.parsers.document import (
    extract_document_text,
    extract_westlake_embedded_html_text,
    split_into_chunks,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_RECHUNK_TYPES = {"charter", "policy", "major_intro", "transfer_policy"}


def _ensure_asyncpg_url(url: str) -> str:
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


def _extract_text(doc: Document) -> str:
    if doc.source_url and "westlake.edu.cn" in doc.source_url:
        return extract_westlake_embedded_html_text(doc.raw_storage_path)
    return extract_document_text(doc.raw_storage_path)


async def rechunk_document(doc: Document, session: AsyncSession, dry_run: bool) -> tuple[int, int]:
    """返回 (旧 chunk 数, 新 chunk 数)。"""
    existing = list(
        (await session.execute(select(Chunk).where(Chunk.document_id == doc.id))).scalars()
    )
    if not existing:
        logger.warning("Document %s has no existing chunks, skipping (需要走全新采集流程)", doc.id)
        return (0, 0)

    # 重切分要保留原有的 province/university_code/source_url/page_number 等元数据，
    # 这些字段不在 rag_documents 表上，只存在于旧 chunk 的 metadata_json 里。
    base_meta = dict(existing[0].metadata_json or {})
    base_meta.pop("chunk_index", None)

    if not doc.raw_storage_path:
        logger.warning("Document %s has no raw_storage_path, skipping", doc.id)
        return (len(existing), len(existing))

    try:
        text = _extract_text(doc)
    except Exception:
        logger.exception("Failed to extract text for document %s, skipping", doc.id)
        return (len(existing), len(existing))

    if not text.strip():
        logger.warning("Document %s produced empty text, skipping", doc.id)
        return (len(existing), len(existing))

    new_contents = split_into_chunks(text, document_type=doc.type)
    if not new_contents:
        logger.warning("Document %s produced 0 chunks after re-chunking, skipping (guard against silent data loss)", doc.id)
        return (len(existing), len(existing))

    logger.info("Document %s (%s): %d -> %d chunks", doc.id, doc.type, len(existing), len(new_contents))
    if dry_run:
        return (len(existing), len(new_contents))

    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    for index, content in enumerate(new_contents):
        session.add(
            Chunk(
                document_id=doc.id,
                content=content,
                metadata_json={**base_meta, "chunk_index": index},
                embedding=None,
                embedding_model=None,
            )
        )
    await session.commit()
    return (len(existing), len(new_contents))


async def run(doc_id: str | None, all_docs: bool, dry_run: bool) -> None:
    db_url = _ensure_asyncpg_url(settings.database_url)
    engine = create_async_engine(db_url, echo=False)

    # expire_on_commit=False：每个 document 处理完都会 commit 一次，默认行为会让
    # session 里其它已加载的 Document 对象（比如 --all 一次性查出来的整个列表）在
    # 下一次 commit 后失效，下一轮循环访问 doc.id 时触发同步上下文里的隐式懒加载，
    # 在 asyncpg 下会直接抛 MissingGreenlet。
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if doc_id:
            doc = await session.get(Document, doc_id)
            if doc is None:
                logger.error("Document %s not found", doc_id)
                return
            docs = [doc]
        elif all_docs:
            result = await session.execute(
                select(Document).where(Document.type.in_(_RECHUNK_TYPES), Document.deleted_at.is_(None))
            )
            docs = list(result.scalars().all())
        else:
            logger.error("Specify --doc-id or --all (可加 --dry-run 先看对比统计)")
            return

        total_old = 0
        total_new = 0
        for doc in docs:
            old_count, new_count = await rechunk_document(doc, session, dry_run)
            total_old += old_count
            total_new += new_count

        logger.info("Total: %d documents, %d -> %d chunks", len(docs), total_old, total_new)

        if dry_run:
            logger.info("Dry-run 完成，未写库。")
            await engine.dispose()
            return

        logger.info("Starting embedding pass for re-chunked content...")
        embedded = await embed_pending_chunks(session)
        logger.info("Embedded %d chunks", embedded)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-chunk existing rag_documents with the fixed splitting logic")
    parser.add_argument("--doc-id", help="Re-chunk a single document by ID")
    parser.add_argument("--all", action="store_true", help="Re-chunk all charter/policy/major_intro/transfer_policy documents")
    parser.add_argument("--dry-run", action="store_true", help="Only print before/after chunk counts, do not write to DB")
    args = parser.parse_args()

    asyncio.run(run(args.doc_id, args.all, args.dry_run))
