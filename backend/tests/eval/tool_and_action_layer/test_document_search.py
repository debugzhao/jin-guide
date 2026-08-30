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
from app.engine.document_search import (
    EXCERPT_MAX_CHARS,
    _truncate_at_sentence_boundary,
    search_school_documents,
)


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


class TestExcerptTruncation:
    """回归宁波大学"临床医学拔尖人才创新班"case：学制/学位/专业特色排在 chunk
    第 400 字符之后，旧的 EXCERPT_MAX_CHARS=400 硬截断会把这些字段整段砍掉，
    还会在词中间切断产生转写错字（"精神病学"被砍成"精神医学"）。
    见 rag模块核心问题.md「线上 bug 2」。"""

    def test_short_content_is_not_truncated(self):
        content = "学 制：五年\n授予学位：医学学士学位"
        assert _truncate_at_sentence_boundary(content, EXCERPT_MAX_CHARS) == content

    def test_truncates_at_last_sentence_boundary_not_mid_word(self):
        content = "第一句话结束。第二句被硬切开还没完"
        truncated = _truncate_at_sentence_boundary(content, 10)
        assert truncated == "第一句话结束。"

    def test_falls_back_to_hard_cut_when_no_sentence_boundary(self):
        content = "无标点连续文本" * 100
        truncated = _truncate_at_sentence_boundary(content, 50)
        assert truncated == content[:50]

    def test_field_beyond_old_400_char_limit_now_survives(self):
        """关键字段起始位置故意超过旧阈值 400，新阈值下必须完整出现在 excerpt 里。"""
        noise = "培养目标：" + "详情内容" * 100 + "。"
        assert len(noise) > 400
        content = noise + "学 制：五年。授予学位：医学学士学位。"
        truncated = _truncate_at_sentence_boundary(content, EXCERPT_MAX_CHARS)
        assert "学 制：五年" in truncated
        assert "授予学位：医学学士学位" in truncated


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
        raw_chunks = [{"chunk_id": "c1", "document_id": "d1", "content": "学费" * 700, "similarity": 0.9}]
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
        # 摘录必须被截断，不能把整个 chunk 内容（可能远超 1200 字符）原样怼给模型
        assert len(chunk["excerpt"]) <= 1200


class TestEntityAnchorFusion:
    """
    2026-08-25 东华大学"学费"问题真实复现过：query 里没提校名时，Cohere 对同一个
    chunk 的打分能从 0.5+ 掉到 0.004，比明显无关内容还低——根因是 SQL 已经把候选
    限定在这所学校范围内这件事，Cohere 精排并不知道，chunk 原文自己也经常不会
    重复"这段属于哪所学校"。这里验证 query 和候选文档在送去 rerank_evidence 之前
    都被强制拼上了校名，且最终呈现给用户的摘录里不能带着这个人工拼接的前缀。
    """

    @pytest.mark.asyncio
    async def test_rerank_evidence_receives_query_and_content_anchored_with_university_name(self):
        db = _make_db(university_row=_university(name="东华大学"))
        raw_chunks = [{"chunk_id": "c1", "document_id": "d1", "content": "学费标准为6500元", "similarity": 0.6}]
        captured = {}

        async def _capture_rerank(query, chunks, top_n=3):
            captured["query"] = query
            captured["chunks"] = chunks
            return ToolResponse.success("ok", {"chunks": []})

        with (
            patch("app.engine.document_search.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.document_search.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": raw_chunks})),
            ),
            patch("app.engine.document_search.rerank_evidence", new=_capture_rerank),
        ):
            await search_school_documents(db, "东华大学", "学费标准是多少")

        assert captured["query"] == "东华大学学费标准是多少"
        assert captured["chunks"][0]["content"] == "东华大学：学费标准为6500元"

    @pytest.mark.asyncio
    async def test_final_excerpt_does_not_leak_the_injected_university_prefix(self):
        db = _make_db(university_row=_university(name="东华大学"), document_title_rows=[])
        raw_chunks = [{"chunk_id": "c1", "document_id": "d1", "content": "学费标准为6500元", "similarity": 0.6}]
        # 模拟 rerank_evidence 真实返回时，content 字段带着我们拼进去的前缀
        reranked = {**raw_chunks[0], "content": "东华大学：学费标准为6500元", "rerank_score": 0.9, "metadata": {}}

        with (
            patch("app.engine.document_search.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.document_search.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": raw_chunks})),
            ),
            patch(
                "app.engine.document_search.rerank_evidence",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": [reranked]})),
            ),
        ):
            result = await search_school_documents(db, "东华大学", "学费标准是多少")

        assert result.is_success
        assert result.data["chunks"][0]["excerpt"] == "学费标准为6500元"
        assert "东华大学：" not in result.data["chunks"][0]["excerpt"]


class TestFallbackQueryRetry:
    """精排对 query 措辞敏感——模型自己拼的 query 有时打不出分（这次真实案例：
    "2026年本科学费标准"没提校名，Cohere 打了 0.0045 分，全部被 0.3 下限挡掉），
    用调用方传入的用户原始提问再试一次，不需要重新跑 embedding/向量检索。"""

    @pytest.mark.asyncio
    async def test_retries_with_fallback_query_when_primary_query_yields_nothing(self):
        db = _make_db(
            university_row=_university(name="东华大学"),
            document_title_rows=[MagicMock(id="d1", title="东华大学2026年本科招生章程")],
        )
        raw_chunks = [{"chunk_id": "c1", "document_id": "d1", "content": "学费标准为6500元", "similarity": 0.6}]
        reranked_hit = {**raw_chunks[0], "rerank_score": 0.7, "metadata": {}}

        call_queries = []

        async def _rerank_side_effect(query, chunks, top_n=3):
            call_queries.append(query)
            if len(call_queries) == 1:
                return ToolResponse.success("ok", {"chunks": []})  # 第一次（模型拼的query）打不出分
            return ToolResponse.success("ok", {"chunks": [reranked_hit]})  # 第二次（原始提问）命中

        with (
            patch("app.engine.document_search.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.document_search.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": raw_chunks})),
            ),
            patch("app.engine.document_search.rerank_evidence", new=_rerank_side_effect),
        ):
            result = await search_school_documents(
                db, "东华大学", "2026年本科学费标准",
                fallback_query="东华大学2026年本科学费标准是多少？",
            )

        assert len(call_queries) == 2, "第一次打不出分应该用 fallback_query 再试一次"
        assert result.is_success
        assert result.data["chunks"][0]["excerpt"] == "学费标准为6500元"

    @pytest.mark.asyncio
    async def test_no_retry_when_fallback_query_same_as_query(self):
        """fallback_query 和 query 完全一样时再试一次没有意义，不该多打一次 API。"""
        db = _make_db(university_row=_university())
        raw_chunks = [{"chunk_id": "c1", "document_id": "d1", "content": "内容", "similarity": 0.6}]
        call_count = 0

        async def _rerank_always_empty(query, chunks, top_n=3):
            nonlocal call_count
            call_count += 1
            return ToolResponse.success("ok", {"chunks": []})

        with (
            patch("app.engine.document_search.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.document_search.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": raw_chunks})),
            ),
            patch("app.engine.document_search.rerank_evidence", new=_rerank_always_empty),
        ):
            result = await search_school_documents(db, "东华大学", "学费", fallback_query="学费")

        assert call_count == 1
        assert result.is_partial

    @pytest.mark.asyncio
    async def test_no_retry_when_fallback_query_not_provided(self):
        db = _make_db(university_row=_university())
        raw_chunks = [{"chunk_id": "c1", "document_id": "d1", "content": "内容", "similarity": 0.6}]
        call_count = 0

        async def _rerank_always_empty(query, chunks, top_n=3):
            nonlocal call_count
            call_count += 1
            return ToolResponse.success("ok", {"chunks": []})

        with (
            patch("app.engine.document_search.embed_text", new=AsyncMock(return_value=[0.1, 0.2])),
            patch(
                "app.engine.document_search.vector_search",
                new=AsyncMock(return_value=ToolResponse.success("ok", {"chunks": raw_chunks})),
            ),
            patch("app.engine.document_search.rerank_evidence", new=_rerank_always_empty),
        ):
            result = await search_school_documents(db, "东华大学", "学费")

        assert call_count == 1
        assert result.is_partial
