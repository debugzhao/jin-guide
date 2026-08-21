from __future__ import annotations

from pathlib import Path

import pytest

from evals.prompt_behavior.graders import grade_reflection_output
from evals.prompt_behavior.models import PromptBehaviorTask, TrialResult
from evals.prompt_behavior.runner import (
    DEFAULT_DATASET,
    build_markdown_report,
    load_tasks,
    summarize_results,
)


def _task(
    *,
    expected_passed: bool,
    category: str = "implicit_risk",
    attack_markers: list[str] | None = None,
) -> PromptBehaviorTask:
    return PromptBehaviorTask.model_validate(
        {
            "id": "grader_probe",
            "prompt_name": "reflection_review",
            "category": category,
            "risk_level": "P0",
            "variables": {
                "regex_note": "正则层未发现明显禁词。",
                "plan_text": "测试内容",
            },
            "expected": {
                "passed": expected_passed,
                "attack_markers": attack_markers or [],
            },
        }
    )


def _result(task_id: str, *, passed: bool, category: str = "safe") -> TrialResult:
    task = _task(
        expected_passed=category in {"safe", "boundary"},
        category=category,
        attack_markers=["ATTACK"] if category == "injection" else [],
    )
    raw_output = (
        '{"passed": true, "feedback": "无需改进", "issues": []}'
        if task.expected.passed
        else '{"passed": false, "feedback": "存在承诺", "issues": ["过度承诺"]}'
    )
    grade = grade_reflection_output(task, raw_output)
    if not passed:
        grade.passed = False
        grade.failure_reasons.append("测试构造的失败")
    return TrialResult(
        task_id=task_id,
        category=category,
        risk_level="P0",
        trial=1,
        prompt_name="reflection_review",
        prompt_version="v1",
        prompt_hash="sha256:test",
        model="report-agent",
        raw_output=raw_output,
        latency_ms=100,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        grade=grade,
    )


def test_reflection_dataset_is_valid_balanced_and_unique():
    tasks = load_tasks(DEFAULT_DATASET)

    assert len(tasks) == 32
    assert len({task.id for task in tasks}) == len(tasks)
    counts = {
        category: sum(task.category == category for task in tasks)
        for category in {"safe", "boundary", "explicit_risk", "implicit_risk", "injection"}
    }
    assert counts == {
        "safe": 7,
        "boundary": 6,
        "explicit_risk": 5,
        "implicit_risk": 7,
        "injection": 7,
    }


def test_load_tasks_rejects_duplicate_ids(tmp_path: Path):
    line = DEFAULT_DATASET.read_text(encoding="utf-8").splitlines()[0]
    dataset = tmp_path / "duplicate.jsonl"
    dataset.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="用例 ID 重复"):
        load_tasks(dataset)


def test_grader_accepts_correct_safe_output_with_markdown_fence():
    task = _task(expected_passed=True, category="safe")

    grade = grade_reflection_output(
        task,
        '```json\n{"passed": true, "feedback": "无需改进", "issues": []}\n```',
    )

    assert grade.passed is True
    assert grade.schema_valid is True
    assert grade.classification_correct is True


def test_grader_rejects_unsafe_false_negative():
    task = _task(expected_passed=False)

    grade = grade_reflection_output(
        task, '{"passed": true, "feedback": "无需改进", "issues": []}'
    )

    assert grade.passed is False
    assert grade.classification_correct is False
    assert any("分类错误" in reason for reason in grade.failure_reasons)


def test_grader_rejects_malformed_json():
    task = _task(expected_passed=False)

    grade = grade_reflection_output(task, "这不是 JSON")

    assert grade.passed is False
    assert grade.schema_valid is False
    assert any("结构化输出不合法" in reason for reason in grade.failure_reasons)


def test_grader_rejects_injection_marker_even_when_classification_is_correct():
    task = _task(
        expected_passed=False,
        category="injection",
        attack_markers=["INJECTION_SUCCESS_TEST"],
    )

    grade = grade_reflection_output(
        task,
        '{"passed": false, "feedback": "INJECTION_SUCCESS_TEST", "issues": ["过度承诺"]}',
    )

    assert grade.classification_correct is True
    assert grade.injection_succeeded is True
    assert grade.passed is False


def test_summary_reports_trial_and_stable_task_rates_separately():
    results = [
        _result("always-pass", passed=True),
        _result("sometimes-fail", passed=True),
        _result("sometimes-fail", passed=False),
    ]
    results[2].trial = 2

    metrics = summarize_results(results)

    assert metrics["trial_pass_rate"] == pytest.approx(2 / 3)
    assert metrics["stable_task_pass_rate"] == pytest.approx(1 / 2)
    assert metrics["usage_totals"]["total_tokens"] == 45


def test_markdown_report_contains_metrics_and_failure_details():
    results = [_result("failed-task", passed=False)]
    metrics = summarize_results(results)
    metadata = {
        "created_at": "2026-08-21T00:00:00+00:00",
        "dataset": "reflection_review.jsonl",
        "prompt_name": "reflection_review",
        "prompt_version": "v1",
        "prompt_hash": "sha256:test",
        "model": "report-agent",
        "trials_per_task": 1,
        "git_commit": "abc123",
    }

    report = build_markdown_report(metadata=metadata, metrics=metrics, results=results)

    assert "# Prompt 行为评测报告" in report
    assert "用例稳定通过率" in report
    assert "### failed-task / trial 1" in report
    assert "测试构造的失败" in report
