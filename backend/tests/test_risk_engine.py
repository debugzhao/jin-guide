"""
志愿表风险引擎单元测试
"""
import pytest

from app.engine.risk_engine import (
    check_safety_adequacy,
    check_gradient,
    check_crowding,
    check_rejected_major,
    run_all_checks,
)


def _make(
    name: str,
    major: str,
    tier: str = "target",
    rank_gap: float = 0,
    major_category: str = "",
) -> dict:
    return {
        "university_name": name,
        "major_name": major,
        "tier": tier,
        "rank_gap": rank_gap,
        "major_category": major_category or major[:3],
        "overall_score": 60.0,
    }


# ── check_safety_adequacy ─────────────────────────────────────────────────────

class TestSafetyAdequacy:
    def test_no_safe_is_high(self):
        candidates = [_make("A大", "计算机", tier="rush")] * 5
        items = check_safety_adequacy(candidates)
        assert len(items) == 1
        assert items[0]["severity"] == "high"
        assert items[0]["risk_type"] == "safety_adequacy"

    def test_few_safe_is_high(self):
        safe = [_make(f"保底{i}", "护理", tier="safe") for i in range(5)]
        rush = [_make(f"冲刺{i}", "计算机", tier="rush") for i in range(20)]
        items = check_safety_adequacy(safe + rush)
        assert any(i["severity"] == "high" for i in items)

    def test_sufficient_safe_ok(self):
        safe = [_make(f"保{i}", "护理", tier="safe") for i in range(12)]
        items = check_safety_adequacy(safe)
        assert items == []


# ── check_gradient ────────────────────────────────────────────────────────────

class TestGradient:
    def test_compressed_medium(self):
        # 5 rush schools with rank_gap difference < 2000
        candidates = [
            _make("A", "计算机", tier="rush", rank_gap=-2000 - i * 300)
            for i in range(5)
        ]
        items = check_gradient(candidates)
        assert len(items) == 1
        assert items[0]["severity"] == "medium"

    def test_wide_gaps_ok(self):
        candidates = [
            _make("A", "计算机", tier="rush", rank_gap=-2000),
            _make("B", "软件", tier="rush", rank_gap=-6000),
            _make("C", "人工智能", tier="rush", rank_gap=-11000),
        ]
        items = check_gradient(candidates)
        assert items == []

    def test_single_school_per_tier_ok(self):
        candidates = [
            _make("A", "计算机", tier="rush", rank_gap=-3000),
            _make("B", "护理", tier="safe", rank_gap=5000),
        ]
        items = check_gradient(candidates)
        assert items == []


# ── check_crowding ────────────────────────────────────────────────────────────

class TestCrowding:
    def test_crowding_high(self):
        cs = [_make(f"院{i}", "计算机", major_category="计算机") for i in range(40)]
        cs += [_make(f"院{i}", "历史学", major_category="历史学") for i in range(10)]
        items = check_crowding(cs)
        assert any(i["risk_type"] == "major_crowding" and i["severity"] == "medium"
                   for i in items)

    def test_crowding_ok(self):
        cs = []
        for cat in ["计算机", "电子", "机械", "材料", "化工"]:
            cs += [_make(f"{cat}{i}", cat, major_category=cat) for i in range(4)]
        items = check_crowding(cs)
        # 4/20=20% < threshold → no medium items
        assert all(i["severity"] != "medium" for i in items)

    def test_empty_candidates(self):
        assert check_crowding([]) == []


# ── check_rejected_major ──────────────────────────────────────────────────────

class TestRejectedMajor:
    def test_violation_found(self):
        cs = [_make("医科大", "临床医学", tier="target")]
        items = check_rejected_major(cs, ["临床医学"])
        assert len(items) == 1
        assert items[0]["severity"] == "high"
        assert "临床医学" in items[0]["targets"][0]

    def test_no_rejection_list_ok(self):
        cs = [_make("医科大", "临床医学", tier="target")]
        items = check_rejected_major(cs, [])
        assert items == []

    def test_partial_match(self):
        cs = [_make("理工大", "软件工程", tier="rush")]
        items = check_rejected_major(cs, ["软件"])
        assert len(items) == 1

    def test_no_match(self):
        cs = [_make("师范大", "数学教育", tier="safe")]
        items = check_rejected_major(cs, ["临床医学", "法学"])
        assert items == []


# ── run_all_checks ────────────────────────────────────────────────────────────

class TestRunAllChecks:
    def test_overall_high_when_no_safe(self):
        cs = [_make("A大", "计算机", tier="rush")] * 20
        items, level = run_all_checks(cs, [])
        assert level == "high"

    def test_overall_low_clean(self):
        # Diverse majors to avoid crowding; all safe with wide rank gaps
        majors = ["护理", "会计", "土木", "电子", "机械", "材料", "化工", "法学",
                  "英语", "数学", "物理", "历史", "地理", "生物", "金融"]
        cs = [_make(f"保{i}", majors[i], tier="safe", rank_gap=3000 + i * 3000)
              for i in range(15)]
        items, level = run_all_checks(cs, [])
        assert level == "low"
        assert items == []

    def test_combined_risks(self):
        safe = [_make(f"保{i}", "护理", tier="safe", rank_gap=5000 + i * 3000)
                for i in range(12)]
        rush = [_make("医大", "临床医学", tier="rush", rank_gap=-3000)]
        items, level = run_all_checks(safe + rush, rejected_majors=["临床医学"])
        assert level == "high"
        types = {i["risk_type"] for i in items}
        assert "rejected_major" in types
