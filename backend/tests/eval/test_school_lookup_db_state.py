"""
「数据库最终状态是否符合预期」这一类 state-checker grader，针对
app/engine/school_lookup.py 的三个确定性 SQL 工具（intake_chat 的事实性查询
全部要经过它们，禁止让 LLM 凭记忆回答分数/选科要求）。

用内存 sqlite 而不是真实 Postgres：University/AdmissionScore/SubjectRequirement
三张表只用到了跨方言通用的列类型（String/Integer/Boolean/JSON），换成 sqlite
不影响被测逻辑，却能让这组测试完全不依赖外部数据库、可以在任何环境下秒级跑完。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.engine.school_lookup import (
    compare_universities,
    lookup_subject_requirement,
    lookup_university_score,
)
from app.models.admission import AdmissionScore, SubjectRequirement, University


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    # 只建这三张表：Base.metadata 里可能还注册了带 pgvector Vector 列的表（如 Chunk），
    # 那些列类型在 sqlite 上无法建表，显式传 tables= 避免误建到不相关的表。
    University.metadata.create_all(
        engine,
        tables=[University.__table__, AdmissionScore.__table__, SubjectRequirement.__table__],
    )
    session_factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db: Session) -> dict[str, University]:
    zzu = University(name="郑州大学", city="郑州", is_985=False, is_211=True)
    henu = University(name="河南大学", city="开封", is_985=False, is_211=False)
    zju = University(name="浙江大学", city="杭州", is_985=True, is_211=True)
    db.add_all([zzu, henu, zju])
    db.flush()

    db.add_all([
        AdmissionScore(
            university_id=zzu.id, year=2023, province="河南", batch="本科批",
            subject_type="physics", min_score=598, min_rank=32000,
            avg_score=605, avg_rank=28000,
        ),
        AdmissionScore(
            university_id=zzu.id, year=2022, province="河南", batch="本科批",
            subject_type="physics", min_score=590, min_rank=35000,
            avg_score=600, avg_rank=30000,
        ),
    ])
    db.add(
        SubjectRequirement(
            university_id=zju.id,
            major_name="计算机科学与技术",
            required_subjects=["物理"],
            optional_subjects=["化学", "生物"],
            optional_required_count=1,
            restricted_subjects=[],
            medical_restrictions={"color_blind": "不招"},
        )
    )
    db.add(
        SubjectRequirement(
            university_id=zju.id,
            major_name="临床医学",
            required_subjects=["物理", "化学"],
            optional_subjects=[],
            optional_required_count=0,
            restricted_subjects=["色弱"],
            medical_restrictions={},
        )
    )
    db.commit()
    return {"郑州大学": zzu, "河南大学": henu, "浙江大学": zju}


# ── lookup_university_score ─────────────────────────────────────────────────────

class TestLookupUniversityScoreState:
    def test_returns_records_ordered_by_year_descending(self, db, seeded):
        result = lookup_university_score(db, "郑州大学", "河南")

        assert result.is_success
        years = [r["year"] for r in result.data["records"]]
        assert years == [2023, 2022]
        assert result.data["is_211"] is True
        assert result.data["is_985"] is False

    def test_filters_to_a_single_year_when_year_is_given(self, db, seeded):
        result = lookup_university_score(db, "郑州大学", "河南", year=2022)

        assert result.is_success
        assert len(result.data["records"]) == 1
        assert result.data["records"][0]["min_score"] == 590

    def test_unknown_university_returns_error_not_partial(self, db, seeded):
        result = lookup_university_score(db, "不存在的大学", "河南")

        assert result.is_error
        assert result.error_info["code"] == "UNIVERSITY_NOT_FOUND"

    def test_existing_university_without_matching_scores_returns_partial(self, db, seeded):
        """河南大学存在，但没有录取分数记录——必须是 PARTIAL 而不是 ERROR 或假装 SUCCESS。"""
        result = lookup_university_score(db, "河南大学", "河南")

        assert result.is_partial
        assert result.data["records"] == []

    def test_wrong_province_yields_no_records_even_if_university_has_scores_elsewhere(
        self, db, seeded
    ):
        result = lookup_university_score(db, "郑州大学", "湖北")

        assert result.is_partial
        assert result.data["records"] == []


# ── lookup_subject_requirement ──────────────────────────────────────────────────

class TestLookupSubjectRequirementState:
    def test_returns_all_majors_when_major_name_not_given(self, db, seeded):
        result = lookup_subject_requirement(db, "浙江大学")

        assert result.is_success
        assert len(result.data["requirements"]) == 2

    def test_filters_by_major_name(self, db, seeded):
        result = lookup_subject_requirement(db, "浙江大学", major_name="计算机")

        assert result.is_success
        assert len(result.data["requirements"]) == 1
        req = result.data["requirements"][0]
        assert req["required_subjects"] == ["物理"]
        assert req["medical_restrictions"] == {"color_blind": "不招"}

    def test_unknown_university_returns_error(self, db, seeded):
        result = lookup_subject_requirement(db, "不存在的大学")

        assert result.is_error

    def test_known_university_without_matching_major_returns_partial(self, db, seeded):
        result = lookup_subject_requirement(db, "浙江大学", major_name="哲学")

        assert result.is_partial
        assert result.data["requirements"] == []


# ── compare_universities ─────────────────────────────────────────────────────────

class TestCompareUniversitiesState:
    def test_aggregates_latest_score_per_university(self, db, seeded):
        result = compare_universities(db, ["郑州大学", "河南大学"], "河南")

        assert result.is_success
        by_name = {u["university_name"]: u for u in result.data["universities"]}
        assert by_name["郑州大学"]["year"] == 2023  # 最新一年
        assert by_name["郑州大学"]["min_score"] == 598
        # 河南大学存在但没有录取记录，字段应为 None 而不是被静默丢弃
        assert by_name["河南大学"]["min_score"] is None

    def test_reports_not_found_universities_as_partial(self, db, seeded):
        result = compare_universities(db, ["郑州大学", "不存在的大学"], "河南")

        assert result.is_partial
        assert result.data["not_found"] == ["不存在的大学"]
        assert len(result.data["universities"]) == 1

    def test_all_universities_missing_returns_error(self, db, seeded):
        result = compare_universities(db, ["不存在1", "不存在2"], "河南")

        assert result.is_error
        assert result.error_info["code"] == "NO_UNIVERSITY_FOUND"
