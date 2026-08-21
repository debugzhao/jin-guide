from __future__ import annotations

from data_pipeline.config import load_pipeline_config
from data_pipeline.discovery import discover_links
from data_pipeline.parsers import (
    TabularDocument,
    parse_admission_score_rows,
    parse_admission_plan_rows,
    parse_rank_segment_rows,
)
from data_pipeline.records import Provenance
from data_pipeline.validators import attach_min_ranks, validate_records


def _provenance(data_type: str = "admission_score") -> Provenance:
    return Provenance(
        source_url="https://www.jseea.cn/example.pdf",
        source_document_id="doc-1",
        source_title="官方样本",
        year=2025,
        authority_level="official",
        collected_at="2026-08-21T00:00:00+00:00",
        parser_version=f"{data_type}_v1",
    )


def test_discovers_supported_official_attachments_and_deduplicates() -> None:
    html = """
    <a href="/upload/score-physics.pdf">物理类投档线</a>
    <a href="/upload/score-physics.pdf#page=1">重复链接</a>
    <a href="javascript:void(0)">忽略</a>
    <a href="https://example.com/notes.txt">忽略格式</a>
    """
    links = discover_links(
        html,
        base_url="https://www.jseea.cn/page.html",
        title_pattern="物理|重复",
    )
    assert [item.url for item in links] == [
        "https://www.jseea.cn/upload/score-physics.pdf"
    ]


def test_parses_whitelisted_admission_scores_and_attaches_exact_rank() -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    score_doc = TabularDocument(
        rows=[
            ["院校代号", "院校、专业组", "投档最低分"],
            ["1101", "南京大学07专业组(化学)", "661", "239", "120"],
            ["9999", "非白名单大学01专业组(不限)", "600"],
            ["1104", "南京理工大学05专业组(化学)(中外合作办学)", "616"],
        ],
        page_or_sheet=[1, 1, 1, 2],
    )
    scores = parse_admission_score_rows(
        score_doc,
        subject_type="physics",
        provenance=_provenance(),
        config=config,
    )
    assert len(scores) == 2
    assert scores[0].university_code == "10284"
    assert scores[0].major_group_code == "07"
    assert scores[0].min_score == 661
    assert scores[1].admission_type == "中外合作办学"

    rank_doc = TabularDocument(
        rows=[["分数", "人数", "累计人数"], ["661", "20", "1000"], ["660", "30", "1030"]],
        page_or_sheet=[1, 1, 1],
    )
    ranks = parse_rank_segment_rows(
        rank_doc, subject_type="physics", provenance=_provenance("rank")
    )
    enriched = attach_min_ranks(scores, ranks)
    assert enriched[0].min_rank == 1000
    assert enriched[1].min_rank is None
    validated = validate_records(enriched, config)
    assert validated[0].status == "valid"
    assert validated[1].status == "needs_review"


def test_rank_validation_rejects_duplicates_and_non_monotonic_rows() -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    document = TabularDocument(
        rows=[["661", "1000"], ["660", "900"], ["660", "900"]],
        page_or_sheet=[1, 1, 1],
    )
    ranks = parse_rank_segment_rows(
        document, subject_type="physics", provenance=_provenance("rank")
    )
    results = validate_records(ranks, config)
    assert results[0].status == "valid"
    assert results[1].status == "rejected"
    assert results[2].status == "rejected"


def test_rank_parser_handles_two_three_column_tables_side_by_side() -> None:
    document = TabularDocument(
        rows=[["682", "144", "7121", "642", "389", "33069"]],
        page_or_sheet=[1],
    )
    records = parse_rank_segment_rows(
        document, subject_type="physics", provenance=_provenance("rank")
    )
    assert [(item.score, item.cumulative_rank) for item in records] == [
        (682, 7121),
        (642, 33069),
    ]


def test_parses_admission_plan_with_forward_filled_university_and_group() -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    document = TabularDocument(
        rows=[
            ["院校名称", "院校代号", "院校专业组", "专业代号", "专业名称", "计划人数", "学费", "学制", "备注"],
            ["南京大学", "1101", "07", "01", "人工智能", "8", "6380", "4", ""],
            ["", "", "", "02", "软件工程", "6", "6380", "4", "在鼓楼校区学习"],
            ["非白名单大学", "9999", "01", "01", "示例专业", "10", "5000", "4", ""],
        ],
        page_or_sheet=[1, 1, 1, 1],
    )
    records = parse_admission_plan_rows(
        document,
        subject_type="physics",
        provenance=_provenance("plan"),
        config=config,
    )
    assert len(records) == 2
    assert records[0].university_code == "10284"
    assert records[1].major_group_code == "07"
    assert records[1].major_name == "软件工程"
