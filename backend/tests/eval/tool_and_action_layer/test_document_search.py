"""
app/engine/document_search.py（IntakeAgent 的 RAG 检索工具 search_school_documents）
的编排逻辑测试——真正的 vector_search/rerank_evidence/embed_text 需要 pgvector 和
外部 embedding/Cohere API，这里全部 mock 掉，只验证：找不到院校、院校没有 code、
检索为空这几个分支的降级行为，以及命中时把 chunk 正确格式化成 data.chunks（含引用来源）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tool_response import ToolResponse
from app.engine.document_search import search_school_documents


def _make_db(university_row, document_title_rows: list | None = None):
    """构造一个假的 AsyncSession：第一次 execute() 命中 _find_university 的查询，
    第二次命中 _load_document_titles 的查询——顺序对应 search_school_documents 里
    真实的调用顺序。"""
    university_result = MagicMock()
    university_result.scalars.return_value.first.return_value = university_row

    titles_result = MagicMock()
    titles_result.all.return_value = document_title_rows or []

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[university_result, titles_result])
    return db


def _university(code: str | None = "10255", name: str = "东华大学"):
    university = MagicMock()
    university.code = code
    university.name = name
    return university


class TestSearchSchoolDocuments:
    @pytest.mark.asyncio
    async def test_unknown_university_returns_error(self):
        db = _make_db(university_row=None)

        result = await search_school_documents(db, "不存在的大学", "学费")

        assert result.is_error
        assert result.error_info["code"] == "UNIVERSITY_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_university_without_code_returns_partial(self):
        """University.code 是关联 rag_chunks.metadata_json.university_code 的唯一键，
        没有 code 就没法限定检索范围，必须提前短路，不能带着 None 传给 vector_search。"""
        db = _make_db(university_row=_university(code=None))

        result = await search_school_documents(db, "某民办高校", "学费")

        assert result.is_partial
        assert result.data["chunks"] == []

    @pytest.mark.asyncio
    async def test_no_vector_search_hits_returns_partial(self):
        db = _make_db(university_row=_university())

        with (
            patch("app.engine.document_search.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.document_search.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": []})),
            ),
        ):
            result = await search_school_documents(db, "东华大学", "住宿条件")

        assert result.is_partial
        assert result.data["chunks"] == []

    @pytest.mark.asyncio
    async def test_rerank_filtering_everything_out_returns_partial(self):
        db = _make_db(university_row=_university())
        raw_chunks = [{"chunk_id": "c1", "document_id": "d1", "content": "无关内容", "similarity": 0.4}]

        with (
            patch("app.engine.document_search.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.document_search.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": raw_chunks})),
            ),
            patch(
                "app.engine.document_search.rerank_evidence",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": []})),
            ),
        ):
            result = await search_school_documents(db, "东华大学", "学费")

        assert result.is_partial
        assert result.data["chunks"] == []

    @pytest.mark.asyncio
    async def test_success_formats_chunks_with_title_and_citation(self):
        university = _university()
        db = _make_db(
            university_row=university,
            document_title_rows=[MagicMock(id="d1", title="东华大学2026年本科招生章程")],
        )
        raw_chunks = [{"chunk_id": "c1", "document_id": "d1", "content": "学费" * 300, "similarity": 0.9}]
        reranked_chunk = {
            **raw_chunks[0],
            "rerank_score": 0.95,
            "metadata": {"source_url": "https://dhu.example/charter.htm", "section_title": "第二十一条"},
        }

        with (
            patch("app.engine.document_search.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.document_search.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": raw_chunks})),
            ),
            patch(
                "app.engine.document_search.rerank_evidence",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": [reranked_chunk]})),
            ),
        ):
            result = await search_school_documents(db, "东华大学", "各专业学费标准")

        assert result.is_success
        assert len(result.data["chunks"]) == 1
        chunk = result.data["chunks"][0]
        assert chunk["title"] == "东华大学2026年本科招生章程"
        assert chunk["source_url"] == "https://dhu.example/charter.htm"
        assert chunk["section_title"] == "第二十一条"
        # 摘录必须被截断，不能把整个 chunk 内容（可能超过 1200 字符）原样怼给模型
        assert len(chunk["excerpt"]) <= 400
