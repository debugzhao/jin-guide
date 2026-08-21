from __future__ import annotations

from collections import Counter
from typing import Any

from evals.prompt_behavior.models import TrialResult


HIGHER_IS_BETTER = (
    "unsafe_recall",
    "safe_acceptance_rate",
    "schema_valid_rate",
    "stable_task_pass_rate",
)
LOWER_IS_BETTER = ("injection_success_rate",)


def compare_versions(
    *,
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    baseline_results: list[TrialResult],
    candidate_results: list[TrialResult],
) -> dict[str, Any]:
    """比较两版 Prompt 的六项核心指标；任一核心退化即判 candidate 更差。"""
    metric_deltas: dict[str, dict[str, Any]] = {}
    improvements: list[str] = []
    regressions: list[str] = []

    for metric in HIGHER_IS_BETTER + LOWER_IS_BETTER:
        baseline_value = baseline_metrics.get(metric)
        candidate_value = candidate_metrics.get(metric)
        if baseline_value is None or candidate_value is None:
            direction = "not_comparable"
            delta = None
        else:
            delta = candidate_value - baseline_value
            if abs(delta) < 1e-12:
                direction = "same"
            elif (metric in HIGHER_IS_BETTER and delta > 0) or (
                metric in LOWER_IS_BETTER and delta < 0
            ):
                direction = "better"
                improvements.append(metric)
            else:
                direction = "worse"
                regressions.append(metric)
        metric_deltas[metric] = {
            "baseline": baseline_value,
            "candidate": candidate_value,
            "delta": delta,
            "direction": direction,
        }

    if regressions:
        verdict = "worse"
    elif improvements:
        verdict = "better"
    else:
        verdict = "equivalent"

    baseline_by_key = {
        (result.task_id, result.trial): result for result in baseline_results
    }
    candidate_by_key = {
        (result.task_id, result.trial): result for result in candidate_results
    }
    if baseline_by_key.keys() != candidate_by_key.keys():
        missing_from_candidate = sorted(baseline_by_key.keys() - candidate_by_key.keys())
        missing_from_baseline = sorted(candidate_by_key.keys() - baseline_by_key.keys())
        raise ValueError(
            "新旧版本 Trial 不一致，无法配对比较: "
            f"candidate 缺少={missing_from_candidate}, baseline 缺少={missing_from_baseline}"
        )

    paired_counts: Counter[str] = Counter()
    changed_trials: list[dict[str, Any]] = []
    for key in sorted(baseline_by_key):
        baseline = baseline_by_key[key]
        candidate = candidate_by_key[key]
        if baseline.grade.passed and candidate.grade.passed:
            outcome = "both_passed"
        elif baseline.grade.passed:
            outcome = "baseline_only"
        elif candidate.grade.passed:
            outcome = "candidate_only"
        else:
            outcome = "both_failed"
        paired_counts[outcome] += 1
        if outcome in {"baseline_only", "candidate_only"}:
            changed_trials.append(
                {
                    "task_id": key[0],
                    "trial": key[1],
                    "outcome": outcome,
                    "baseline_failure_reasons": baseline.grade.failure_reasons,
                    "candidate_failure_reasons": candidate.grade.failure_reasons,
                }
            )

    return {
        "verdict": verdict,
        "improvements": improvements,
        "regressions": regressions,
        "metric_deltas": metric_deltas,
        "paired_counts": {
            name: paired_counts.get(name, 0)
            for name in ("both_passed", "baseline_only", "candidate_only", "both_failed")
        },
        "changed_trials": changed_trials,
    }


def build_comparison_markdown(
    *,
    metadata: dict[str, Any],
    comparison: dict[str, Any],
) -> str:
    labels = {
        "unsafe_recall": "风险内容召回率",
        "safe_acceptance_rate": "正常内容放行率",
        "schema_valid_rate": "JSON Schema 合法率",
        "injection_success_rate": "注入攻击成功率",
        "stable_task_pass_rate": "用例稳定通过率",
    }
    verdict_labels = {"better": "候选版本更好", "worse": "候选版本更差", "equivalent": "两版相当"}
    lines = [
        "# Prompt 版本对比报告",
        "",
        f"- 运行时间：{metadata['created_at']}",
        f"- Prompt：`{metadata['prompt_name']}`",
        f"- 基线版本：`{metadata['baseline_version']}`",
        f"- 候选版本：`{metadata['candidate_version']}`",
        f"- 模型：`{metadata['model']}`",
        f"- 每条用例运行次数：{metadata['trials_per_task']}",
        "",
        f"## 结论：{verdict_labels[comparison['verdict']]}",
        "",
        "规则：任一核心指标退化即判候选版本更差；无退化且至少一项提升才判更好。",
        "",
        "## 六项核心指标",
        "",
        "| 指标 | 基线 | 候选 | 差值 | 方向 |",
        "|---|---:|---:|---:|---|",
    ]
    for metric, values in comparison["metric_deltas"].items():
        baseline = values["baseline"]
        candidate = values["candidate"]
        delta = values["delta"]
        baseline_text = "N/A" if baseline is None else f"{baseline:.2%}"
        candidate_text = "N/A" if candidate is None else f"{candidate:.2%}"
        delta_text = "N/A" if delta is None else f"{delta:+.2%}"
        lines.append(
            f"| {labels[metric]} | {baseline_text} | {candidate_text} | {delta_text} | "
            f"{values['direction']} |"
        )

    paired = comparison["paired_counts"]
    lines.extend(
        [
            "",
            "## 逐 Trial 配对",
            "",
            f"- 两版都通过：{paired['both_passed']}",
            f"- 仅基线通过：{paired['baseline_only']}",
            f"- 仅候选通过：{paired['candidate_only']}",
            f"- 两版都失败：{paired['both_failed']}",
            "",
            "## 结果发生变化的 Trial",
            "",
        ]
    )
    if not comparison["changed_trials"]:
        lines.append("无。")
    else:
        for item in comparison["changed_trials"]:
            lines.append(
                f"- `{item['task_id']}` trial {item['trial']}：{item['outcome']}；"
                f"基线失败原因={item['baseline_failure_reasons']}；"
                f"候选失败原因={item['candidate_failure_reasons']}"
            )
    return "\n".join(lines).rstrip() + "\n"
