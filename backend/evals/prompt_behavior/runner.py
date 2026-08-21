# reflection_review Prompt 的行为评测 CLI：加载 JSONL 用例数据集，对每条用例真实调用
# reflection_review 模型跑 N 次 trial，用 graders.grade_reflection_output 打分，
# 汇总通过率/召回率/延迟等指标，落地 results.json + report.md 两份报告。
# 核心函数：load_tasks（加载并校验数据集）、run_trial（单次模型调用+打分）、
# summarize_results（汇总统计指标）、build_markdown_report（生成 md 报告）、
# execute（CLI 主流程）。
# 用法：cd backend && python -m evals.prompt_behavior.runner [--dataset PATH]
#      [--trials N] [--prompt-version V] [--category C ...] [--limit N]
#      [--baseline-version V1 --candidate-version V2]
#      [--output-dir DIR] [--dry-run 仅校验数据集/Prompt/筛选条件，不调用真实模型]
from __future__ import annotations

import argparse
import asyncio
import json
import math
import subprocess
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agent.llm_client import call_chat_completion
from app.prompts import prompt_registry
from evals.prompt_behavior.comparison import build_comparison_markdown, compare_versions
from evals.prompt_behavior.graders import grade_reflection_output
from evals.prompt_behavior.models import PromptBehaviorTask, TrialResult


MODULE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = MODULE_ROOT / "datasets" / "reflection_review.jsonl"
DEFAULT_REPORT_ROOT = Path(__file__).resolve().parents[2] / "eval_reports" / "prompt_behavior"


def load_tasks(path: Path) -> list[PromptBehaviorTask]:
    tasks: list[PromptBehaviorTask] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            task = PromptBehaviorTask.model_validate_json(line)
        except (ValueError, ValidationError) as exc:
            raise ValueError(f"{path}:{line_number} 用例格式错误: {exc}") from exc
        if task.id in seen_ids:
            raise ValueError(f"{path}:{line_number} 用例 ID 重复: {task.id}")
        seen_ids.add(task.id)
        tasks.append(task)
    if not tasks:
        raise ValueError(f"评测数据集为空: {path}")
    return tasks


def summarize_results(results: list[TrialResult]) -> dict[str, Any]:
    if not results:
        raise ValueError("没有 Trial 结果可汇总")

    total = len(results)
    safe_categories = {"safe", "boundary"}
    unsafe_categories = {"explicit_risk", "implicit_risk", "injection"}
    safe_results = [result for result in results if result.category in safe_categories]
    unsafe_results = [result for result in results if result.category in unsafe_categories]
    injection_results = [result for result in results if result.category == "injection"]

    grouped: dict[str, list[TrialResult]] = defaultdict(list)
    for result in results:
        grouped[result.task_id].append(result)

    latencies = sorted(result.latency_ms for result in results)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    usage_totals: dict[str, int] = defaultdict(int)
    for result in results:
        for key, value in result.usage.items():
            if isinstance(value, int):
                usage_totals[key] += value

    category_metrics: dict[str, dict[str, Any]] = {}
    for category in sorted({result.category for result in results}):
        category_results = [result for result in results if result.category == category]
        category_metrics[category] = {
            "trials": len(category_results),
            "passed": sum(result.grade.passed for result in category_results),
            "pass_rate": sum(result.grade.passed for result in category_results)
            / len(category_results),
        }

    stable_tasks = sum(
        all(result.grade.passed for result in task_results)
        for task_results in grouped.values()
    )
    return {
        "total_tasks": len(grouped),
        "total_trials": total,
        "passed_trials": sum(result.grade.passed for result in results),
        "trial_pass_rate": sum(result.grade.passed for result in results) / total,
        "schema_valid_rate": sum(result.grade.schema_valid for result in results) / total,
        "classification_accuracy": sum(
            result.grade.classification_correct for result in results
        )
        / total,
        "unsafe_recall": (
            sum(result.grade.classification_correct for result in unsafe_results)
            / len(unsafe_results)
            if unsafe_results
            else None
        ),
        "safe_acceptance_rate": (
            sum(
                result.grade.schema_valid
                and result.grade.parsed_output is not None
                and result.grade.parsed_output["passed"] is True
                for result in safe_results
            )
            / len(safe_results)
            if safe_results
            else None
        ),
        "safe_false_positive_rate": (
            sum(
                result.grade.schema_valid
                and result.grade.parsed_output is not None
                and result.grade.parsed_output["passed"] is False
                for result in safe_results
            )
            / len(safe_results)
            if safe_results
            else None
        ),
        "injection_success_rate": (
            sum(result.grade.injection_succeeded for result in injection_results)
            / len(injection_results)
            if injection_results
            else None
        ),
        "stable_tasks": stable_tasks,
        "stable_task_pass_rate": stable_tasks / len(grouped),
        "average_latency_ms": round(sum(latencies) / len(latencies)),
        "p95_latency_ms": latencies[p95_index],
        "usage_totals": dict(usage_totals),
        "category_metrics": category_metrics,
    }


async def run_trial(
    task: PromptBehaviorTask, *, trial: int, prompt_version: str | None = None
) -> TrialResult:
    spec = prompt_registry.get(task.prompt_name, prompt_version)
    started_at = time.perf_counter()
    raw_output = ""
    usage: dict = {}
    error: str | None = None
    try:
        request_body = {
            **spec.request_options(eval_task_id=task.id, eval_trial=str(trial)),
            "messages": [
                {"role": "system", "content": spec.render("system")},
                {"role": "user", "content": spec.render("user", **task.variables)},
            ],
        }
        response = await call_chat_completion(
            request_body, timeout=spec.model.timeout_seconds
        )
        raw_output = response["choices"][0]["message"]["content"]
        usage = response.get("usage") or {}
    except Exception as exc:  # 单条失败不能中止整批评测
        error = f"{type(exc).__name__}: {exc}"

    latency_ms = max(0, round((time.perf_counter() - started_at) * 1000))
    grade = grade_reflection_output(task, raw_output)
    if error:
        grade.failure_reasons.insert(0, f"模型调用失败: {error}")
        grade.passed = False
    return TrialResult(
        task_id=task.id,
        category=task.category,
        risk_level=task.risk_level,
        trial=trial,
        prompt_name=spec.prompt_name,
        prompt_version=spec.version,
        prompt_hash=spec.content_hash,
        model=spec.model.alias,
        raw_output=raw_output,
        latency_ms=latency_ms,
        usage=usage,
        error=error,
        grade=grade,
    )


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _format_rate(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2%}"


def build_markdown_report(
    *, metadata: dict[str, Any], metrics: dict[str, Any], results: list[TrialResult]
) -> str:
    lines = [
        "# Prompt 行为评测报告",
        "",
        f"- 运行时间：{metadata['created_at']}",
        f"- 数据集：`{metadata['dataset']}`",
        f"- Prompt：`{metadata['prompt_name']}@{metadata['prompt_version']}`",
        f"- Prompt hash：`{metadata['prompt_hash']}`",
        f"- 模型：`{metadata['model']}`",
        f"- 每条用例运行次数：{metadata['trials_per_task']}",
        f"- Git commit：`{metadata.get('git_commit') or 'unknown'}`",
        "",
        "## 汇总指标",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| Task 数 | {metrics['total_tasks']} |",
        f"| Trial 数 | {metrics['total_trials']} |",
        f"| Trial 成功率 | {_format_rate(metrics['trial_pass_rate'])} |",
        f"| 用例稳定通过率 | {_format_rate(metrics['stable_task_pass_rate'])} |",
        f"| JSON Schema 合法率 | {_format_rate(metrics['schema_valid_rate'])} |",
        f"| 分类准确率 | {_format_rate(metrics['classification_accuracy'])} |",
        f"| 风险样本召回率 | {_format_rate(metrics['unsafe_recall'])} |",
        f"| 正常内容放行率 | {_format_rate(metrics['safe_acceptance_rate'])} |",
        f"| 合规误杀率 | {_format_rate(metrics['safe_false_positive_rate'])} |",
        f"| 注入攻击成功率 | {_format_rate(metrics['injection_success_rate'])} |",
        f"| 平均延迟 | {metrics['average_latency_ms']} ms |",
        f"| P95 延迟 | {metrics['p95_latency_ms']} ms |",
        "",
        "## 分类结果",
        "",
        "| 分类 | Trial | 通过 | 通过率 |",
        "|---|---:|---:|---:|",
    ]
    for category, category_metric in metrics["category_metrics"].items():
        lines.append(
            f"| {category} | {category_metric['trials']} | {category_metric['passed']} | "
            f"{_format_rate(category_metric['pass_rate'])} |"
        )

    usage = metrics["usage_totals"]
    lines.extend(
        [
            "",
            "## Token 用量",
            "",
            f"- Prompt tokens：{usage.get('prompt_tokens', 0)}",
            f"- Completion tokens：{usage.get('completion_tokens', 0)}",
            f"- Total tokens：{usage.get('total_tokens', 0)}",
            "",
            "## 失败 Trial",
            "",
        ]
    )
    failures = [result for result in results if not result.grade.passed]
    if not failures:
        lines.append("无失败 Trial。")
    else:
        for result in failures:
            lines.extend(
                [
                    f"### {result.task_id} / trial {result.trial}",
                    "",
                    f"- 分类：`{result.category}`；风险：`{result.risk_level}`",
                    f"- 原因：{'；'.join(result.grade.failure_reasons)}",
                    f"- 原始输出：`{json.dumps(result.raw_output, ensure_ascii=False)}`",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


async def execute(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.dataset)
    if args.category:
        tasks = [task for task in tasks if task.category in args.category]
    if args.limit is not None:
        tasks = tasks[: args.limit]
    if not tasks:
        raise ValueError("筛选后没有可运行的评测用例")

    comparison_mode = bool(args.baseline_version and args.candidate_version)
    versions = (
        [args.baseline_version, args.candidate_version]
        if comparison_mode
        else [args.prompt_version]
    )
    specs = [prompt_registry.get("reflection_review", version) for version in versions]
    if comparison_mode and specs[0].model != specs[1].model:
        raise ValueError("新旧 Prompt 必须使用完全相同的模型参数，当前配置不一致")

    if args.dry_run:
        counts: dict[str, int] = defaultdict(int)
        for task in tasks:
            counts[task.category] += 1
        print(
            json.dumps(
                {
                    "status": "validated",
                    "dataset": str(args.dataset),
                    "tasks": len(tasks),
                    "categories": dict(sorted(counts.items())),
                    "prompts": [f"{spec.prompt_name}@{spec.version}" for spec in specs],
                    "model": specs[0].model.alias,
                    "mode": "compare" if comparison_mode else "single",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    created_at = datetime.now(UTC)
    output_dir = args.output_dir or (
        DEFAULT_REPORT_ROOT / created_at.strftime("%Y%m%dT%H%M%SZ")
    )
    output_dir.mkdir(parents=True, exist_ok=False)

    if comparison_mode:
        baseline_results = await _run_tasks(
            tasks, trials=args.trials, prompt_version=args.baseline_version, label="baseline"
        )
        candidate_results = await _run_tasks(
            tasks, trials=args.trials, prompt_version=args.candidate_version, label="candidate"
        )
        baseline_metrics = summarize_results(baseline_results)
        candidate_metrics = summarize_results(candidate_results)
        comparison = compare_versions(
            baseline_metrics=baseline_metrics,
            candidate_metrics=candidate_metrics,
            baseline_results=baseline_results,
            candidate_results=candidate_results,
        )
        metadata = {
            "created_at": created_at.isoformat(),
            "dataset": str(args.dataset),
            "prompt_name": "reflection_review",
            "baseline_version": specs[0].version,
            "baseline_hash": specs[0].content_hash,
            "candidate_version": specs[1].version,
            "candidate_hash": specs[1].content_hash,
            "model": specs[0].model.alias,
            "trials_per_task": args.trials,
            "git_commit": _git_commit(),
        }
        payload = {
            "metadata": metadata,
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "comparison": comparison,
            "baseline_results": [result.model_dump(mode="json") for result in baseline_results],
            "candidate_results": [result.model_dump(mode="json") for result in candidate_results],
        }
        (output_dir / "comparison.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "comparison.md").write_text(
            build_comparison_markdown(metadata=metadata, comparison=comparison),
            encoding="utf-8",
        )
        print(f"版本对比完成：{output_dir}")
        candidate_p0_passed = all(
            result.grade.passed for result in candidate_results if result.risk_level == "P0"
        )
        return 0 if comparison["verdict"] != "worse" and candidate_p0_passed else 1

    spec = specs[0]
    results = await _run_tasks(
        tasks, trials=args.trials, prompt_version=args.prompt_version, label=spec.version
    )
    metrics = summarize_results(results)
    metadata = {
        "created_at": created_at.isoformat(),
        "dataset": str(args.dataset),
        "prompt_name": spec.prompt_name,
        "prompt_version": spec.version,
        "prompt_hash": spec.content_hash,
        "model": spec.model.alias,
        "trials_per_task": args.trials,
        "git_commit": _git_commit(),
    }
    payload = {
        "metadata": metadata,
        "metrics": metrics,
        "results": [result.model_dump(mode="json") for result in results],
    }
    (output_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(
        build_markdown_report(metadata=metadata, metrics=metrics, results=results),
        encoding="utf-8",
    )
    print(f"评测完成：{output_dir}")
    # CI 只拿 P0（明确风险/注入类）用例的通过情况做红绿灯，P1/P2 失败不阻断流水线，
    # 避免边界样本的偶发抖动挡住发布——报告里仍能看到全量结果供人工复核。
    return 0 if all(result.grade.passed for result in results if result.risk_level == "P0") else 1


async def _run_tasks(
    tasks: list[PromptBehaviorTask], *, trials: int, prompt_version: str | None, label: str
) -> list[TrialResult]:
    results: list[TrialResult] = []
    for task_index, task in enumerate(tasks, 1):
        for trial in range(1, trials + 1):
            print(
                f"[{label}] [{task_index}/{len(tasks)}] {task.id} trial={trial}",
                flush=True,
            )
            results.append(
                await run_trial(task, trial=trial, prompt_version=prompt_version)
            )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 reflection_review Prompt 行为评测")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    # --trials 3 表示每个评测用例都调用真实模型运行 3 次。
    # 它用于观察模型的随机性和稳定性：例如同一用例 3 次中通过 2 次，则单次成功率为 66.7%，但该用例不算“稳定通过”。
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--baseline-version", default=None)
    parser.add_argument("--candidate-version", default=None)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验数据集、Prompt 和筛选条件，不调用真实模型",
    )
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials 必须大于等于 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须大于等于 1")
    if bool(args.baseline_version) != bool(args.candidate_version):
        parser.error("--baseline-version 和 --candidate-version 必须同时提供")
    if args.prompt_version and args.baseline_version:
        parser.error("单版本 --prompt-version 不能和版本对比参数同时使用")
    if args.baseline_version == args.candidate_version and args.baseline_version:
        parser.error("基线版本和候选版本不能相同")
    return args


def main() -> int:
    return asyncio.run(execute(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
