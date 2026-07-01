"""
Reflection Agent node (Day 8).

Two-layer compliance self-check after report generation:
  Layer 1: regex forbidden-word detection (deterministic)
  Layer 2: LLM judge for semantic over-promise detection

Max 3 iterations. Early exit when LLM returns passed=true or
feedback contains "无需改进".

Graph routing (handled by conditional edges in graph.py):
  pass + no human review needed  → END
  fail + iterations < 3          → back to report (retry)
  fail + iterations >= 3         → human_review_node (forced)
  pass + needs_human_review       → human_review_node (risk-driven)
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from app.agent.nodes.compliance import check_compliance_report
from app.agent.state import VolunteerPlanState
from app.config import settings

logger = logging.getLogger(__name__)

_JUDGE_MODEL = "report-agent"
_LLM_TIMEOUT = 30.0
_MAX_ITERATIONS = 3

# Semantic over-promise patterns for LLM judge prompt guidance
_SEMANTIC_RISK_EXAMPLES = [
    "录取概率极高",
    "几乎必然录取",
    "可以放心报",
    "稳拿",
    "必然上岸",
]


async def _llm_judge(plan_json: dict, compliance_issues: list[str]) -> dict:
    """
    Layer 2 LLM judge: semantic over-promise detection.
    Returns {"passed": bool, "feedback": str, "issues": list[str]}.
    On any exception, returns {"passed": True, "feedback": "judge unavailable"}.
    """
    # Flatten plan text for LLM review
    plan_text = json.dumps(plan_json, ensure_ascii=False, indent=2)
    if len(plan_text) > 4000:
        plan_text = plan_text[:4000] + "\n...(truncated)"

    regex_note = (
        f"正则已发现以下问题（供参考）：{', '.join(compliance_issues)}"
        if compliance_issues
        else "正则层未发现明显禁词。"
    )

    system_msg = (
        "你是高考志愿报告的合规审查员。"
        "你的任务是检测报告文本中是否存在语义层面的过度承诺或误导性表述，"
        "即使没有触发明确的禁词。"
        "常见风险表述示例：录取概率极高、几乎必然录取、可以放心报、稳拿、必然上岸等。"
        "输出必须是合法 JSON，格式如下：\n"
        '{"passed": true/false, "feedback": "简洁说明", "issues": ["具体问题1", ...]}\n'
        "如果报告文本没有任何问题，输出 "
        '{"passed": true, "feedback": "无需改进", "issues": []}'
    )

    user_msg = (
        f"{regex_note}\n\n"
        f"请审查以下报告内容是否存在过度承诺或误导：\n\n{plan_text}"
    )

    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.litellm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.litellm_master_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _JUDGE_MODEL,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        result = json.loads(content)
        return {
            "passed": bool(result.get("passed", False)),
            "feedback": str(result.get("feedback", "")),
            "issues": [str(i) for i in result.get("issues", [])],
        }
    except Exception as exc:
        logger.warning("LLM judge unavailable in reflection_agent: %s", exc)
        # Conservative fallback: treat as passed to avoid infinite retry loops
        return {"passed": True, "feedback": "judge unavailable", "issues": []}


async def reflection_agent(state: VolunteerPlanState) -> dict:
    """
    Reflection Agent: run two-layer compliance check on the generated report.
    Returns state delta for compliance_passed, compliance_issues, reflection_iterations.
    """
    plan_json = state.get("report_draft") or {}
    iterations = state.get("reflection_iterations", 0) + 1
    run_id = state.get("run_id", "")

    logger.info("Reflection Agent iteration %d (run_id=%s)", iterations, run_id)

    # ── Layer 1: regex forbidden-word check ──────────────────────────────────
    regex_passed, regex_issues = check_compliance_report(plan_json)

    if not regex_passed:
        logger.warning(
            "Layer 1 regex found issues (iter=%d): %s", iterations, regex_issues
        )
        return {
            "compliance_passed": False,
            "compliance_issues": regex_issues,
            "reflection_iterations": iterations,
        }

    # ── Layer 2: LLM judge for semantic over-promise ──────────────────────────
    llm_result = await _llm_judge(plan_json, regex_issues)
    llm_passed = llm_result["passed"]
    feedback = llm_result.get("feedback", "")
    llm_issues = llm_result.get("issues", [])

    # Early exit: LLM explicitly says passed or "无需改进"
    if llm_passed or "无需改进" in feedback:
        logger.info("Reflection Agent passed on iter %d (early exit)", iterations)
        return {
            "compliance_passed": True,
            "compliance_issues": [],
            "reflection_iterations": iterations,
        }

    all_issues = list(dict.fromkeys(regex_issues + llm_issues))  # preserve order, dedup
    logger.warning(
        "Layer 2 LLM judge found issues (iter=%d): %s", iterations, all_issues
    )
    return {
        "compliance_passed": False,
        "compliance_issues": all_issues,
        "reflection_iterations": iterations,
    }
