"""
Reflection Agent 节点（Day 8）。

报告生成后的两层合规自检：
  第一层：正则禁词检测（确定性）
  第二层：LLM 判定，检测语义层面的过度承诺

最多 3 轮迭代。当 LLM 返回 passed=true，或 feedback 包含
"无需改进" 时提前结束。

图路由规则（由 graph.py 中的条件边处理）：
  compliance_passed         → END
  fail + iterations < 3     → 回到 report（重试）
  max iterations exceeded   → END（带警告的尽力交付）

人工复核（HITL）已在 v1.1 移除，reflection 不再有 human_review 分支。
"""
from __future__ import annotations

import json
import logging
import re

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.agent.nodes.compliance import check_compliance_report
from app.agent.state import VolunteerPlanState
from app.config import settings
from app.prompts import prompt_registry
from app.prompts.tracing import track_prompt_invocation

logger = logging.getLogger(__name__)

_PROMPT = prompt_registry.get("reflection_review")
_JUDGE_MODEL = _PROMPT.model.alias
_LLM_TIMEOUT = _PROMPT.model.timeout_seconds
_MAX_ITERATIONS = 3

# 用于引导 LLM 判定 Prompt 的语义过度承诺示例
_SEMANTIC_RISK_EXAMPLES = [
    "录取概率极高",
    "几乎必然录取",
    "可以放心报",
    "稳拿",
    "必然上岸",
]


class ReflectionReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    feedback: str
    issues: list[str]

    @model_validator(mode="after")
    def passing_result_cannot_contain_issues(self) -> "ReflectionReviewOutput":
        if self.passed and self.issues:
            raise ValueError("passed=true 时 issues 必须为空")
        return self


async def _llm_judge(
    plan_json: dict, compliance_issues: list[str], *, run_id: str | None = None
) -> dict:
    """
    第二层 LLM 判定：检测语义层面的过度承诺。
    返回 {"passed": bool, "feedback": str, "issues": list[str]}。
    出现任何异常时都返回失败结果，避免一个不可用的审查器"默认通过"报告。
    """
    # 把方案文本展平，供 LLM 审查
    plan_text = json.dumps(plan_json, ensure_ascii=False, indent=2)
    if len(plan_text) > 4000:
        plan_text = plan_text[:4000] + "\n...(truncated)"

    regex_note = (
        f"正则已发现以下问题（供参考）：{', '.join(compliance_issues)}"
        if compliance_issues
        else "正则层未发现明显禁词。"
    )

    system_msg = _PROMPT.render("system")
    user_msg = _PROMPT.render("user", regex_note=regex_note, plan_text=plan_text)

    try:
        async with track_prompt_invocation(_PROMPT, agent_run_id=run_id) as invocation:
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.litellm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.litellm_master_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        **invocation.request_options(),
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": user_msg},
                        ],
                    },
                )
                resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        # 去掉 markdown 代码块围栏
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        result = ReflectionReviewOutput.model_validate_json(content)
        return {
            "passed": result.passed,
            "feedback": result.feedback,
            "issues": result.issues,
        }
    except Exception as exc:
        logger.warning("LLM judge unavailable in reflection_agent: %s", exc)
        # 高考志愿属于高风险决策；审查不可用不能等价为内容安全，交给图的有限重试与
        # 失败终态处理，避免未审查报告被标记为 completed。
        return {
            "passed": False,
            "feedback": "合规审查暂时不可用",
            "issues": ["合规审查服务不可用"],
        }


async def reflection_agent(state: VolunteerPlanState) -> dict:
    """
    Reflection Agent：对生成的报告执行两层合规检查。
    返回 compliance_passed、compliance_issues、reflection_iterations 的状态增量。
    """
    plan_json = state.get("report_draft") or {}
    iterations = state.get("reflection_iterations", 0) + 1
    run_id = state.get("run_id", "")

    logger.info("Reflection Agent iteration %d (run_id=%s)", iterations, run_id)

    # ── 第一层：正则禁词检查 ──────────────────────────────────
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

    # ── 第二层：LLM 判定语义层面的过度承诺 ──────────────────────────
    llm_result = await _llm_judge(plan_json, regex_issues, run_id=run_id)
    llm_passed = llm_result["passed"]
    feedback = llm_result.get("feedback", "")
    llm_issues = llm_result.get("issues", [])

    # 只信任结构化 passed=true；自然语言 feedback 不能覆盖失败状态。
    if llm_passed:
        logger.info("Reflection Agent passed on iter %d (early exit)", iterations)
        return {
            "compliance_passed": True,
            "compliance_issues": [],
            "reflection_iterations": iterations,
        }

    all_issues = list(dict.fromkeys(regex_issues + llm_issues))  # 保序去重
    logger.warning(
        "Layer 2 LLM judge found issues (iter=%d): %s", iterations, all_issues
    )
    return {
        "compliance_passed": False,
        "compliance_issues": all_issues,
        "reflection_iterations": iterations,
    }
