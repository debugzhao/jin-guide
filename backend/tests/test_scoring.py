"""
推荐评分引擎单元测试 — 使用 SQLite in-memory
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base
from app.models.admission import AdmissionScore, ProvinceThreshold
from app.engine.scoring import (
    assign_tier,
    compute_admission_score,
    compute_major_fit_score,
    compute_city_family_score,
    compute_cost_risk_score,
    compute_overall_score,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # 只建这一张测试用到的表：Base.metadata 上还挂着用了 JSONB 列的表
    # （notifications/agent_runs/reports/report_conversations），SQLite 编译器
    # 无法渲染 JSONB，全量 create_all 会报 CompileError。
    # compute_admission_score 会查 province_thresholds 取阈值（查无数据时回落默认值，
    # 但表必须存在），故一并建表，不插数据。
    Base.metadata.create_all(
        engine, tables=[AdmissionScore.__table__, ProvinceThreshold.__table__]
    )
    with Session(engine) as session:
        # 3-year data for UNIV_A
        for year, min_rank in [(2023, 30000), (2024, 31000), (2025, 32000)]:
            session.add(AdmissionScore(
                university_id="UNIV_A",
                year=year,
                province="河南",
                batch="本科批",
                subject_type="physics",
                min_rank=min_rank,
                avg_rank=min_rank + 2000,
                max_score=600 + (year - 2023) * 5,
            ))
        # Single-year data for UNIV_B
        session.add(AdmissionScore(
            university_id="UNIV_B",
            year=2025,
            province="河南",
            batch="本科批",
            subject_type="physics",
            min_rank=80000,
        ))
        session.commit()
        yield session


# ── assign_tier ───────────────────────────────────────────────────────────────

class TestAssignTier:
    def test_high_rush(self):
        assert assign_tier(-6000) == "high_rush"

    def test_high_rush_boundary(self):
        assert assign_tier(-5001) == "high_rush"

    def test_rush(self):
        assert assign_tier(-3000) == "rush"

    def test_rush_boundary_lower(self):
        assert assign_tier(-1001) == "rush"

    def test_target_negative(self):
        assert assign_tier(-500) == "target"

    def test_target_positive(self):
        assert assign_tier(1500) == "target"

    def test_target_boundary(self):
        assert assign_tier(2000) == "target"

    def test_safe(self):
        assert assign_tier(3000) == "safe"


# ── compute_admission_score ───────────────────────────────────────────────────

class TestComputeAdmissionScore:
    def test_no_data_fallback(self, db):
        score, gap, tier = compute_admission_score(
            50000, "UNIV_UNKNOWN", "河南", "本科批", "physics", db
        )
        assert score == 50.0
        assert gap == 0.0
        assert tier == "target"

    def test_safe_margin(self, db):
        # student_rank=20000, avg_historical=(30000+31000+32000)/3=31000 → gap=11000 → safe
        score, gap, tier = compute_admission_score(
            20000, "UNIV_A", "河南", "本科批", "physics", db
        )
        assert tier == "safe"
        assert gap > 2000
        assert score > 70

    def test_risky_student(self, db):
        # student_rank=40000, avg=31000 → gap=-9000 → high_rush
        score, gap, tier = compute_admission_score(
            40000, "UNIV_A", "河南", "本科批", "physics", db
        )
        assert tier == "high_rush"
        assert gap < -5000
        assert score < 50

    def test_single_year_stability_fallback(self, db):
        # UNIV_B has only 1 year → stability falls back to 0.8
        score, gap, tier = compute_admission_score(
            80000, "UNIV_B", "河南", "本科批", "physics", db
        )
        assert 0.0 <= score <= 100.0

    def test_score_bounds(self, db):
        # Extreme safe scenario — score must be ≤100
        score, _, _ = compute_admission_score(1, "UNIV_A", "河南", "本科批", "physics", db)
        assert score <= 100.0
        # Extreme risky scenario — score must be ≥0
        score2, _, _ = compute_admission_score(
            999999, "UNIV_A", "河南", "本科批", "physics", db
        )
        assert score2 >= 0.0


# ── compute_major_fit_score ───────────────────────────────────────────────────

class TestComputeMajorFitScore:
    def test_preferred_major_no_rejection(self):
        s = compute_major_fit_score(
            preference_majors=["计算机科学"],
            rejected_majors=[],
            major_name="计算机科学与技术",
            student_subjects=["物理", "化学"],
            required_subjects=["物理"],
        )
        assert s > 80

    def test_rejected_major_penalty(self):
        # With rejection: rejection_penalty=0, so score = pref*0.5 + subject*0.3 + 0*0.2
        # Without rejection: rejection_penalty=100
        s_rejected = compute_major_fit_score(
            preference_majors=[],
            rejected_majors=["临床医学"],
            major_name="临床医学",
            student_subjects=["物理", "化学", "生物"],
        )
        s_clean = compute_major_fit_score(
            preference_majors=[],
            rejected_majors=[],
            major_name="临床医学",
            student_subjects=["物理", "化学", "生物"],
        )
        # Rejected major must score significantly lower than clean
        assert s_rejected < s_clean - 10
        # Rejected major penalty component (0.2 weight) = 0; clean = 100*0.2 = 20 points lower
        assert abs((s_clean - s_rejected) - 20) < 1.0

    def test_no_preference_neutral(self):
        s = compute_major_fit_score(
            preference_majors=[],
            rejected_majors=[],
            major_name="土木工程",
            student_subjects=["物理", "化学"],
        )
        assert 40 <= s <= 80

    def test_subject_fully_matched(self):
        s = compute_major_fit_score(
            preference_majors=[],
            rejected_majors=[],
            major_name="化学工程",
            student_subjects=["物理", "化学"],
            required_subjects=["化学"],
        )
        # subject_match=100 contributes positively
        s2 = compute_major_fit_score(
            preference_majors=[],
            rejected_majors=[],
            major_name="化学工程",
            student_subjects=["物理"],
            required_subjects=["化学"],
        )
        assert s > s2


# ── compute_city_family_score ─────────────────────────────────────────────────

class TestComputeCityFamilyScore:
    def test_preferred_city_within_budget(self):
        s = compute_city_family_score(
            "北京", "北京", ["北京"], "河南", 20000, 12000
        )
        assert s >= 80

    def test_no_preference_home_province(self):
        s = compute_city_family_score("郑州", "河南", [], "河南", 15000, 10000)
        assert s >= 60

    def test_over_budget(self):
        s = compute_city_family_score("上海", "上海", [], "河南", 10000, 50000)
        assert s < 50


# ── compute_cost_risk_score ───────────────────────────────────────────────────

class TestComputeCostRiskScore:
    def test_no_risks(self):
        assert compute_cost_risk_score([]) == 100.0

    def test_high_risk_penalty(self):
        items = [{"severity": "high"}, {"severity": "high"}]
        assert compute_cost_risk_score(items) == 60.0

    def test_clamped_to_zero(self):
        items = [{"severity": "high"}] * 10
        assert compute_cost_risk_score(items) == 0.0


# ── compute_overall_score ─────────────────────────────────────────────────────

class TestComputeOverallScore:
    def test_formula(self):
        s = compute_overall_score(80.0, 70.0, 60.0, 90.0)
        expected = 80 * 0.40 + 70 * 0.25 + 60 * 0.20 + 90 * 0.15
        assert abs(s - expected) < 0.01

    def test_all_hundred(self):
        assert compute_overall_score(100, 100, 100, 100) == 100.0

    def test_all_zero(self):
        assert compute_overall_score(0, 0, 0, 0) == 0.0
