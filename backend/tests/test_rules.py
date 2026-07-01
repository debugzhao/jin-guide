"""
Rule Engine 单元测试
覆盖：check_subject_req / check_medical_restriction /
      check_batch_eligibility / check_budget
状态组合：SUCCESS / PARTIAL / ERROR
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.admission import University, AdmissionScore, SubjectRequirement
from app.agent.tool_response import ToolStatus
from app.engine.rules import (
    check_subject_req,
    check_medical_restriction,
    check_batch_eligibility,
    check_budget,
)


# ── 测试数据库 fixture ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        # 院校 A：有选科要求、有体检限制、学费 5000
        univ_a = University(
            id="univ_a",
            name="测试大学A",
            is_985=True, is_211=True, is_shuangyiliu=True,
            has_medical_program=True,
            annual_tuition_min=5000,
            annual_tuition_max=5000,
        )
        # 院校 B：无特殊要求、学费 15000（高价民办）
        univ_b = University(
            id="univ_b",
            name="测试民办B",
            is_985=False, is_211=False, is_shuangyiliu=False,
            has_medical_program=False,
            annual_tuition_min=15000,
            annual_tuition_max=18000,
        )
        # 院校 C：无学费数据
        univ_c = University(
            id="univ_c",
            name="测试大学C（无学费）",
            is_985=False, is_211=False, is_shuangyiliu=False,
            has_medical_program=False,
            annual_tuition_min=None,
            annual_tuition_max=None,
        )
        session.add_all([univ_a, univ_b, univ_c])

        # 选科要求：计算机（必选物理）
        session.add(SubjectRequirement(
            id="req_cs",
            university_id="univ_a",
            major_name="计算机科学与技术",
            required_subjects=["物理"],
            optional_subjects=[],
            optional_required_count=0,
            restricted_subjects=[],
            medical_restrictions=None,
        ))
        # 选科要求：临床医学（必选物理+化学，体检限制）
        session.add(SubjectRequirement(
            id="req_med",
            university_id="univ_a",
            major_name="临床医学",
            required_subjects=["物理", "化学"],
            optional_subjects=[],
            optional_required_count=0,
            restricted_subjects=[],
            medical_restrictions={"color_blind": "不招", "height_min": 155},
        ))
        # 选科要求：N 选 M（化学/生物选 1）
        session.add(SubjectRequirement(
            id="req_bio",
            university_id="univ_a",
            major_name="食品科学与工程",
            required_subjects=[],
            optional_subjects=["化学", "生物"],
            optional_required_count=1,
            restricted_subjects=[],
            medical_restrictions=None,
        ))

        # 录取分数线：河南 2025 本科批 physics
        for uid, min_r in [("univ_a", 5000), ("univ_b", 200000)]:
            session.add(AdmissionScore(
                id=f"score_{uid}",
                university_id=uid,
                year=2025,
                province="河南",
                batch="本科批",
                subject_type="physics",
                min_score=550,
                min_rank=min_r,
                avg_score=555,
                avg_rank=min_r - 1000,
                max_score=560,
                enrollment_count=100,
            ))
        session.commit()
        yield session


# ═══════════════════════════════════════════════════════════════════════════════
# check_subject_req
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckSubjectReq:
    def test_success_meets_required(self, db):
        """考生选了物理 → 满足计算机选科要求"""
        resp = check_subject_req("univ_a", "计算机科学与技术",
                                 ["物理", "化学", "地理"], db)
        assert resp.status == ToolStatus.SUCCESS
        assert resp.data["eligible"] is True

    def test_error_missing_required(self, db):
        """考生未选物理 → 硬阻断"""
        resp = check_subject_req("univ_a", "计算机科学与技术",
                                 ["历史", "政治", "地理"], db)
        assert resp.status == ToolStatus.ERROR
        assert resp.data["eligible"] is False
        assert "物理" in resp.data["missing"]

    def test_error_missing_one_of_two_required(self, db):
        """考生只选了物理没选化学 → 临床医学硬阻断"""
        resp = check_subject_req("univ_a", "临床医学",
                                 ["物理", "地理", "政治"], db)
        assert resp.status == ToolStatus.ERROR
        assert "化学" in resp.data["missing"]

    def test_success_optional_met(self, db):
        """选了化学 → 满足食品科学 N 选 M"""
        resp = check_subject_req("univ_a", "食品科学与工程",
                                 ["物理", "化学", "地理"], db)
        assert resp.status == ToolStatus.SUCCESS

    def test_error_optional_insufficient(self, db):
        """选了物理地理，既无化学也无生物 → 食品科学阻断"""
        resp = check_subject_req("univ_a", "食品科学与工程",
                                 ["物理", "地理", "政治"], db)
        assert resp.status == ToolStatus.ERROR
        assert resp.data["matched"] == []

    def test_partial_no_data(self, db):
        """专业选科数据不存在 → PARTIAL 降级"""
        resp = check_subject_req("univ_a", "不存在的专业",
                                 ["物理", "化学"], db)
        assert resp.status == ToolStatus.PARTIAL
        assert resp.data["reason"] == "no_data"


# ═══════════════════════════════════════════════════════════════════════════════
# check_medical_restriction
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckMedicalRestriction:
    def test_success_no_restriction(self, db):
        """计算机专业无体检限制 → SUCCESS"""
        resp = check_medical_restriction(
            "univ_a", "计算机科学与技术",
            has_color_blind=True, height_cm=160, has_hearing_impairment=False,
            db=db,
        )
        assert resp.status == ToolStatus.SUCCESS

    def test_error_color_blind_blocks_medicine(self, db):
        """色盲 → 临床医学硬阻断"""
        resp = check_medical_restriction(
            "univ_a", "临床医学",
            has_color_blind=True, height_cm=170, has_hearing_impairment=False,
            db=db,
        )
        assert resp.status == ToolStatus.ERROR
        assert resp.data["eligible"] is False
        assert any("色觉" in v for v in resp.data["violations"])

    def test_error_height_below_minimum(self, db):
        """身高 150cm 低于临床医学要求 155cm → 阻断"""
        resp = check_medical_restriction(
            "univ_a", "临床医学",
            has_color_blind=False, height_cm=150, has_hearing_impairment=False,
            db=db,
        )
        assert resp.status == ToolStatus.ERROR
        assert any("身高" in v for v in resp.data["violations"])

    def test_success_height_exactly_at_minimum(self, db):
        """身高恰好 155cm → 通过"""
        resp = check_medical_restriction(
            "univ_a", "临床医学",
            has_color_blind=False, height_cm=155, has_hearing_impairment=False,
            db=db,
        )
        assert resp.status == ToolStatus.SUCCESS

    def test_partial_no_req_data(self, db):
        """院校 B 专业无选科数据 → SUCCESS（无限制）"""
        resp = check_medical_restriction(
            "univ_b", "软件工程",
            has_color_blind=True, height_cm=155, has_hearing_impairment=False,
            db=db,
        )
        assert resp.status == ToolStatus.SUCCESS
        assert resp.data["reason"] == "no_restriction"


# ═══════════════════════════════════════════════════════════════════════════════
# check_batch_eligibility
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckBatchEligibility:
    def test_success_rank_within_cutoff(self, db):
        """位次 3000 < 批次最高录取位次 200000 → 有资格"""
        resp = check_batch_eligibility(
            student_rank=3000, province="河南", target_batch="本科批",
            year=2025, subject_type="physics", db=db,
        )
        assert resp.status == ToolStatus.SUCCESS
        assert resp.data["eligible"] is True

    def test_error_rank_exceeds_cutoff(self, db):
        """位次 250000 超出最高录取位次 200000 → 不够格"""
        resp = check_batch_eligibility(
            student_rank=250000, province="河南", target_batch="本科批",
            year=2025, subject_type="physics", db=db,
        )
        assert resp.status == ToolStatus.ERROR
        assert resp.data["eligible"] is False

    def test_partial_no_data(self, db):
        """无数据省份 → PARTIAL"""
        resp = check_batch_eligibility(
            student_rank=5000, province="西藏", target_batch="本科批",
            year=2025, subject_type="physics", db=db,
        )
        assert resp.status == ToolStatus.PARTIAL
        assert resp.data["reason"] == "no_data"


# ═══════════════════════════════════════════════════════════════════════════════
# check_budget
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckBudget:
    def test_success_within_budget(self, db):
        """学费 5000，预算 8000 → 通过"""
        resp = check_budget("univ_a", family_budget_per_year=8000, db=db)
        assert resp.status == ToolStatus.SUCCESS
        assert resp.data["within_budget"] is True

    def test_partial_slight_over_budget(self, db):
        """学费 18000，预算 16000（超出 12.5%，< 30%）→ PARTIAL 告警"""
        resp = check_budget("univ_b", family_budget_per_year=16000, db=db)
        assert resp.status == ToolStatus.PARTIAL
        assert resp.data["within_budget"] is False
        assert resp.data["excess_ratio"] < 0.30

    def test_error_far_over_budget(self, db):
        """学费 18000，预算 10000（超出 80%，> 30%）→ ERROR 硬阻断"""
        resp = check_budget("univ_b", family_budget_per_year=10000, db=db)
        assert resp.status == ToolStatus.ERROR
        assert resp.data["within_budget"] is False
        assert resp.data["excess_ratio"] > 0.30

    def test_partial_no_tuition_data(self, db):
        """院校 C 无学费数据 → PARTIAL"""
        resp = check_budget("univ_c", family_budget_per_year=8000, db=db)
        assert resp.status == ToolStatus.PARTIAL
        assert resp.data["reason"] == "no_tuition_data"

    def test_partial_unknown_university(self, db):
        """院校不存在 → PARTIAL"""
        resp = check_budget("nonexistent_id", family_budget_per_year=8000, db=db)
        assert resp.status == ToolStatus.PARTIAL
        assert resp.data["reason"] == "no_data"
