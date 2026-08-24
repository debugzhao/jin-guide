"""
文档检索工具 — 建档前聊天场景（IntakeAgent）专用。

回答"培养方向、专业特色细节、转专业规则、学费分专业标准"这类需要查章程/专业介绍
原文才能回答、`school_lookup.py` 的结构化 SQL 工具覆盖不到的问题——复用主 LangGraph
报告流程同一套 `vector_search`/`rerank_evidence`（含 CircuitBreaker 熔断保护），
只是多包一层"按院校名找到 university_code 再限定检索范围"。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tool_response import ToolResponse
from app.engine.embedding import embed_text
from app.engine.retrieval import rerank_evidence, vector_search
from app.models.admission import University
from app.models.document import Document

RESULT_TOP_N = 3
EXCERPT_MAX_CHARS = 400


async def _find_university(db: AsyncSession, name: str) -> University | None:
    stmt = select(University).where(University.name.ilike(f"%{name}%")).limit(1)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _load_document_titles(db: AsyncSession, document_ids: list[str]) -> dict[str, str]:
    if not document_ids:
        return {}
    stmt = select(Document.id, Document.title).where(Document.id.in_(document_ids))
    rows = (await db.execute(stmt)).all()
    return {row.id: row.title for row in rows}


async def search_school_documents(db: AsyncSession, university_name: str, query: str) -> ToolResponse:
    """按院校名 + 用户问题检索章程/专业介绍/政策文档原文片段（top-3，经 Cohere 精排）。"""
    university = await _find_university(db, university_name)
    if university is None:
        return ToolResponse.error("UNIVERSITY_NOT_FOUND", f"未找到院校「{university_name}」", {})
    if not university.code:
        return ToolResponse.partial(
            text=f"{university.name} 暂无可检索的文档数据",
            data={"university_name": university.name, "chunks": []},
        )

    query_vector = await embed_text(query)
    search_result = await vector_search(query_vector, university_code=university.code, db=db)
    chunks = search_result.data.get("chunks", []) if search_result.is_usable else []
    if not chunks:
        return ToolResponse.partial(
            text=f"{university.name} 暂无与「{query}」相关的文档记录",
            data={"university_name": university.name, "chunks": []},
        )

    rerank_result = await rerank_evidence(query, chunks, top_n=RESULT_TOP_N)
    top_chunks = rerank_result.data.get("chunks", [])
    if not top_chunks:
        return ToolResponse.partial(
            text=f"{university.name} 暂无与「{query}」高度相关的文档内容",
            data={"university_name": university.name, "chunks": []},
        )

    titles = await _load_document_titles(db, [c["document_id"] for c in top_chunks])
    results = [
        {
            "title": titles.get(c["document_id"], ""),
            "excerpt": c["content"][:EXCERPT_MAX_CHARS],
            "source_url": (c.get("metadata") or {}).get("source_url"),
            "section_title": (c.get("metadata") or {}).get("section_title"),
        }
        for c in top_chunks
    ]
    return ToolResponse.success(
        text=f"{university.name} 检索到 {len(results)} 条相关文档片段",
        data={"university_name": university.name, "chunks": results},
    )
