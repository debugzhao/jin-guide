"""
Unit tests for compliance.py — regex forbidden-word detection (PRD M2 Layer 1).
"""
import pytest
from app.agent.nodes.compliance import check_compliance, check_compliance_report


# ── check_compliance ──────────────────────────────────────────────────────────

class TestCheckCompliance:
    def test_clean_text_passes(self):
        assert check_compliance("郑州大学综合评分高，录取稳定，建议考虑") == []

    def test_single_forbidden_word(self):
        assert "必中" in check_compliance("这所学校报了必中，不用担心")

    def test_all_ten_forbidden_words(self):
        phrases = [
            "保证录取", "必中", "精准录取", "包过", "保上",
            "百分百录取", "内部数据", "内部指标", "代替填报", "月薪保证",
        ]
        for phrase in phrases:
            found = check_compliance(f"我们可以{phrase}给你")
            assert phrase in found, f"Expected '{phrase}' to be detected"

    def test_multiple_forbidden_words_in_one_text(self):
        text = "我们有内部数据，保证录取，必中率100%"
        issues = check_compliance(text)
        assert "内部数据" in issues
        assert "保证录取" in issues
        assert "必中" in issues

    def test_deduplication(self):
        text = "必中必中必中"
        issues = check_compliance(text)
        assert issues.count("必中") == 1

    def test_empty_string(self):
        assert check_compliance("") == []

    def test_word_embedded_in_sentence(self):
        assert "包过" in check_compliance("报了这个专业就包过了，放心吧")

    def test_no_partial_match(self):
        # "内部" alone is not forbidden — only exact phrases
        result = check_compliance("这是内部评估报告，供参考")
        assert "内部数据" not in result
        assert "内部指标" not in result


# ── check_compliance_report ───────────────────────────────────────────────────

class TestCheckComplianceReport:
    def test_clean_plan_passes(self):
        plan = {
            "plans": [
                {
                    "type": "balanced",
                    "candidates": [
                        {"university_name": "郑州大学", "recommendation_reasons": ["历史录取稳定", "省内211高校"]}
                    ],
                }
            ]
        }
        passed, issues = check_compliance_report(plan)
        assert passed is True
        assert issues == []

    def test_forbidden_word_in_nested_reason(self):
        plan = {
            "plans": [
                {
                    "candidates": [
                        {"recommendation_reasons": ["精准录取率极高，历史数据支撑"]}
                    ]
                }
            ]
        }
        passed, issues = check_compliance_report(plan)
        assert passed is False
        assert "精准录取" in issues

    def test_forbidden_word_in_description(self):
        plan = {"description": "我们利用内部指标为你定制方案"}
        passed, issues = check_compliance_report(plan)
        assert passed is False
        assert "内部指标" in issues

    def test_empty_plan(self):
        passed, issues = check_compliance_report({})
        assert passed is True
        assert issues == []

    def test_deeply_nested_structure(self):
        plan = {"a": {"b": {"c": ["代替填报服务"]}}}
        passed, issues = check_compliance_report(plan)
        assert passed is False
        assert "代替填报" in issues

    def test_returns_all_unique_violations(self):
        plan = {
            "plans": [
                {"desc": "保证录取"},
                {"desc": "必中"},
                {"desc": "保证录取"},  # duplicate
            ]
        }
        passed, issues = check_compliance_report(plan)
        assert passed is False
        assert len([i for i in issues if i == "保证录取"]) == 1
