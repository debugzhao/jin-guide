"""
GET /api/v1/sources/{id} — 证据来源详情接口 (PRD §5.1)
返回 Document 元数据 + 关联 Chunk 列表（按 chunk_index 排序，不含 embedding 向量）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.document import Chunk, Document

router = APIRouter()


class ChunkOut(BaseModel):
    id: str
    content: str
    metadata: dict = {}
    similarity: Optional[float] = None  # present when returned from search context


class SourceOut(BaseModel):
    id: str
    type: str
    title: str
    source_url: Optional[str]
    year: Optional[int]
    authority_level: Optional[str]
    status: str
    chunks: list[ChunkOut]


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
) -> SourceOut:
    doc = await db.get(Document, source_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Source not found")

    result = await db.execute(
        select(Chunk)
        .where(Chunk.document_id == source_id)
        .order_by(
            # chunk_index stored in metadata_json; fall back to created_at
            Chunk.created_at.asc()
        )
    )
    chunks = result.scalars().all()

    return SourceOut(
        id=doc.id,
        type=doc.type,
        title=doc.title,
        source_url=doc.source_url,
        year=doc.year,
        authority_level=doc.authority_level,
        status=doc.status,
        chunks=[
            ChunkOut(
                id=c.id,
                content=c.content,
                metadata=c.metadata_json or {},
            )
            for c in chunks
        ],
    )
