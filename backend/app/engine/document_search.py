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


async def _rerank_with_entity_anchor(university_name: str, query: str, chunks: list[dict]) -> list[dict]:
    """
    给 query 和候选文档都补上学校名再送去精排。

    Cohere 精排是把 query 和候选 chunk 原文孤立地拿去比对——SQL 已经把候选限定在
    这所学校范围内这件事，精排模型并不知道；chunk 原文本身也经常不会重复"这段属于
    哪所学校"（比如"文科类学费标准为6500元…"这种没有主语的句子很常见）。一旦 query
    里也没提校名，两边都缺了这个实体锚点，精排就会判定"看不出跟这个学校有关"，打出
    接近 0 的分数——即使内容其实完全对得上（2026-08-25 东华大学学费问题真实复现过：
    同一个 chunk，query 里有没有"东华大学"这几个字，Cohere 分数能从 0.5+ 掉到
    0.004，比明显无关的内容分数还低）。这里强制给两边都补上校名，不依赖模型自己
    记得在 query 里写。
    """
    anchored_query = f"{university_name}{query}"
    anchored_chunks = [{**c, "content": f"{university_name}：{c['content']}"} for c in chunks]
    rerank_result = await rerank_evidence(anchored_query, anchored_chunks, top_n=RESULT_TOP_N)
    top_chunks = rerank_result.data.get("chunks", [])

    # 精排结果里的 content 带着上面人工拼接的"学校名："前缀，只是为了让打分更准，
    # 不能把这个前缀泄露到最终呈现给用户的摘录里——用 chunk_id 换回原始内容。
    by_chunk_id = {c["chunk_id"]: c for c in chunks}
    restored = []
    for c in top_chunks:
        original = by_chunk_id.get(c.get("chunk_id"))
        if original is not None:
            restored.append({**c, "content": original["content"]})
    return restored


async def search_school_documents(
    db: AsyncSession,
    university_name: str,
    query: str,
    *,
    fallback_query: str | None = None,
) -> ToolResponse:
    """
    按院校名 + 用户问题检索章程/专业介绍/政策文档原文片段（top-3，经 Cohere 精排）。

    `fallback_query` 是调用方传入的用户原始提问（通常比模型自己拼的 `query` 参数
    更完整自然、更可能包含校名）——第一次精排（用 `query`）如果一条都没命中，
    用它对同一批已召回的 chunks 再试一次精排，不需要重新跑 embedding/向量检索。
    这不是因为向量召回没找到（召回阶段已经证实很少漏），是精排对 query 措辞敏感，
    多一次不同措辞的尝试能显著降低"明明有答案却被判定不相关"的概率。
    """
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

    top_chunks = await _rerank_with_entity_anchor(university.name, query, chunks)
    if not top_chunks and fallback_query and fallback_query != query:
        top_chunks = await _rerank_with_entity_anchor(university.name, fallback_query, chunks)

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
