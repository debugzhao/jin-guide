"""
Report Agent 节点（M2）：LLM 生成推荐理由，
组装 plan_json，做合规检查，落库保存。
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import redis.asyncio as aioredis
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.nodes.compliance import check_compliance_report
from app.agent.state import VolunteerPlanState
from app.config import settings
from app.prompts import prompt_registry
from app.prompts.tracing import track_prompt_invocation

logger = logging.getLogger(__name__)

_PROMPT = prompt_registry.get("report_generation")
_REPORT_MODEL = _PROMPT.model.alias
_MAX_CANDIDATES_FOR_LLM = 12  # 限制数量，避免 Prompt 过大
_LLM_TIMEOUT = _PROMPT.model.timeout_seconds


class ReportGenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasons: dict[str, list[str]]
    condition_commentary: str = ""


async def _push_sse(run_id: str, event: str, data: dict) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.xadd(
            f"sse:{run_id}",
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
        )
        await redis_client.expire(f"sse:{run_id}", 604800)
    finally:
        await redis_client.aclose()


async def _call_llm(messages: list[dict], *, run_id: str | None = None) -> str:
    """调用 LiteLLM 代理生成报告文本。"""
    async with track_prompt_invocation(_PROMPT, agent_run_id=run_id) as invocation:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.litellm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.litellm_master_key}",
                    "Content-Type": "application/json",
                },
                json={**invocation.request_options(), "messages": messages},
            )
            resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _build_llm_prompt(profile: dict, top_candidates: list[dict], has_preferences: bool) -> list[dict]:
    """构建用于生成推荐理由 + 条件点评的 LLM Prompt。"""
    province = profile.get("province", "")
    score = profile.get("score", 0)
    rank = profile.get("rank", 0)
    subjects = profile.get("subjects") or []
    batch = profile.get("batch", "本科批")

    cand_lines = []
    for i, c in enumerate(top_candidates, 1):
        cand_lines.append(
            f"{i}. {c.get('university_name', '')}（{c.get('university_city', '')}）"
            f" - {c.get('major_name', '')} - {c.get('tier', '')}档 - 综合评分{c.get('overall_score', 0)}"
            f" - 预估录取概率{int(c.get('probability', 0)*100)}%"
            f" - 学费{c.get('tuition_per_year', 0):,}元/年"
            + (f" - {'、'.join(c.get('tags', []))}" if c.get('tags') else "")
        )

    candidates_text = "\n".join(cand_lines)

    if has_preferences:
        commentary_instruction = (
            "condition_commentary：指出学生输入条件里的张力或可优化点（例如地域偏好和预算存在冲突），"
            "如果没有明显张力，返回空字符串。"
        )
    else:
        commentary_instruction = (
            "condition_commentary：当前只有基础建档信息（尚未提供预算/城市/专业偏好），"
            "生成一句引导性点评，说明报告会先覆盖更多候选、建议后续补充偏好以收窄范围，不要编造张力。"
        )

    return [
        {"role": "system", "content": _PROMPT.render("system")},
        {
            "role": "user",
            "content": _PROMPT.render(
                "user",
                province=province,
                batch=batch,
                score=score,
                rank=rank,
                subjects="、".join(subjects),
                candidate_count=len(top_candidates),
                candidates=candidates_text,
                commentary_instruction=commentary_instruction,
            ),
        },
    ]


def _parse_llm_reasons(content: str, candidate_count: int) -> tuple[dict[int, list[str]], str]:
    """把 LLM 的响应解析为 (按候选项索引的理由字典, condition_commentary)。"""
    try:
        # 去掉可能存在的 markdown 代码块围栏
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        parsed = ReportGenerationOutput.model_validate_json(text)
        reasons_raw = parsed.reasons
        result: dict[int, list[str]] = {}
        for k, v in reasons_raw.items():
            try:
                idx = int(str(k).strip())
                if isinstance(v, list):
                    result[idx] = [str(r) for r in v[:3]]
            except (ValueError, TypeError):
                pass
        commentary = parsed.condition_commentary.strip()
        return result, commentary
    except (ValueError, ValidationError):
        logger.warning("Failed to parse LLM reasons response")
        return {}, ""


def _build_plan_json(
    scored_candidates: list[dict],
    plans_raw: dict,
    risk_items: list[dict],
    profile: dict,
    condition_commentary: str = "",
) -> dict:
    """从 planner 输出组装最终的 plan_json 结构。"""
    risk_level = "low"
    if any(r.get("severity") == "high" for r in risk_items):
        risk_level = "high"
    elif any(r.get("severity") == "medium" for r in risk_items):
        risk_level = "medium"

    risk_items_out = [
        {
            "level": r.get("severity", "low"),
            "description": r.get("message", ""),
        }
        for r in risk_items
    ]

    plan_descriptions = {
        "conservative": "以稳为主，优先确保录取成功率，适合求稳的考生",
        "balanced": "冲稳保均衡分配，综合性价比最高，AI推荐方案",
        "aggressive": "优先冲击高层次院校，适合心态好的考生",
    }

    plans_out = []
    for plan_type, plan_data in plans_raw.items():
        candidates = plan_data.get("volunteers", [])
        plans_out.append({
            "type": plan_type,
            "label": {"conservative": "保守型", "balanced": "均衡型", "aggressive": "进取型"}.get(
                plan_type, plan_type
            ),
            "description": plan_descriptions.get(plan_type, ""),
            "candidates": candidates,
        })

    return {
        "profile_summary": {
            "province": profile.get("province", ""),
            "score": profile.get("score", 0),
            "rank": profile.get("rank", 0),
            "subjects": profile.get("subjects") or [],
        },
        # 顶层条件点评 (docs/backend-prd-v2.md §6.4)：无明显张力/引导语时为空字符串，
        # 前端约定空字符串等同于 null，不展示该区块。
        "condition_commentary": condition_commentary,
        "risk_level": risk_level,
        "risk_items": risk_items_out,
        "plans": plans_out,
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def report_agent(state: VolunteerPlanState) -> dict:
    run_id = state["run_id"]
    profile = state.get("profile") or {}
    scored_candidates = state.get("scored_candidates") or []
    risk_items = state.get("risk_items") or []
    overall_risk = state.get("overall_risk_level", "medium")
    report_draft = state.get("report_draft") or {}
    plans_raw: dict = report_draft.get("plans_raw") or {}

    await _push_sse(run_id, "node_started", {"node": "report", "message": "正在生成三套方案报告"})

    # ── 1. LLM：生成推荐理由 + 条件点评 ────────
    top_candidates = scored_candidates[:_MAX_CANDIDATES_FOR_LLM]
    llm_reasons: dict[int, list[str]] = {}
    # version=1 且预算/城市/专业偏好都还没填 → "基础版"，走引导性点评而非张力点评
    # (docs/backend-prd-v2.md §6.4)
    has_preferences = bool(
        profile.get("family_budget") or profile.get("city_prefs") or profile.get("major_prefs")
    )
    condition_commentary = ""

    if top_candidates:
        try:
            messages = _build_llm_prompt(profile, top_candidates, has_preferences)
            llm_content = await _call_llm(messages, run_id=run_id)
            llm_reasons, condition_commentary = _parse_llm_reasons(llm_content, len(top_candidates))
        except Exception as exc:
            logger.warning("LLM call failed in report_agent: %s", exc)
            # 兜底方案：从数据直接生成基础理由
            for i, c in enumerate(top_candidates, 1):
                reasons = []
                tier = c.get("tier", "target")
                rank_gap = c.get("rank_gap", 0)
                if tier in ("rush", "high_rush"):
                    reasons.append(f"冲击目标，位次差 {abs(int(rank_gap))} 名，具有挑战性")
                elif tier == "target":
                    reasons.append(f"历史录取位次稳定，当前位次差 {int(rank_gap)} 名，匹配度高")
                else:
                    reasons.append(f"保底院校，安全边际充足，位次差 {int(rank_gap)} 名")
                if c.get("tags"):
                    reasons.append(f"{'、'.join(c['tags'])}高校，综合实力强劲")
                llm_reasons[i] = reasons
            condition_commentary = (
                "" if has_preferences
                else "目前只有基础建档信息，报告会先覆盖更多候选，避免过早收窄；补充预算/城市/专业偏好后可以进一步收敛方案。"
            )

    # 把 LLM 生成的理由附加到候选项上
    enriched_candidates = []
    for i, c in enumerate(scored_candidates, 1):
        c_out = dict(c)
        if i <= _MAX_CANDIDATES_FOR_LLM and i in llm_reasons:
            c_out["recommendation_reasons"] = llm_reasons[i]
        elif not c_out.get("recommendation_reasons"):
            c_out["recommendation_reasons"] = [f"综合评分 {c.get('overall_score', 0)}，{c.get('tier', '')}档位"]
        enriched_candidates.append(c_out)

    # 用补充完理由的候选项更新 plans_raw（planner 用的是 "volunteers" 这个 key）
    if plans_raw:
        univ_to_candidate = {c["university_id"]: c for c in enriched_candidates if "university_id" in c}
        for plan_type, plan_data in plans_raw.items():
            updated_cands = []
            for c in plan_data.get("volunteers", []):
                uid = c.get("university_id", "")
                updated_cands.append(univ_to_candidate.get(uid, c))
            plans_raw[plan_type]["volunteers"] = updated_cands

    # ── 2. 组装 plan_json ────────────────────────────────────────────────────
    plan_json = _build_plan_json(
        enriched_candidates, plans_raw, risk_items, profile, condition_commentary
    )

    # ── 3. 合规检查 ───────────────────────────────────────────────────
    compliance_passed, compliance_issues = check_compliance_report(plan_json)

    if not compliance_passed:
        logger.warning("Compliance issues found: %s", compliance_issues)

    # ── 4. 计算 risk_score（0–100，数值越低越安全） ─────────────────────────
    risk_penalty = {"high": 70, "medium": 45, "low": 20}
    risk_score = float(risk_penalty.get(overall_risk, 45))

    # ── 5. 落库（以 run_id 为 key 的幂等 upsert） ──────────────────────
    # Reflection 在同一次 run 内最多可以把流程路由回这个节点
    # _MAX_REFLECTION_ITERATIONS 次；之前每次都用 uuid4()+INSERT 的写法会导致
    # 早期迭代产生的行在 `reports` 表里变成孤儿记录，还会在 run 真正结束之前
    # 提前触发一次 "completed" SSE 事件（见 docs/memory-architecture.md
    # §六 P1）。现在一个 run_id 精确对应一行 Report —— 之后的迭代是覆盖更新
    # 而不是插入新行，终态 SSE 事件则交给 worker 的 finalize 步骤负责发送，
    # 只有整张图（包括重试）都跑完才会触发。
    report_id = str(uuid4())
    db_saved = False
    try:
        from sqlalchemy import select

        from app.database import async_session_maker
        from app.models.report import Report

        async with async_session_maker() as db:
            existing = await db.execute(
                select(Report).where(Report.run_id == run_id, Report.deleted_at.is_(None))
            )
            report = existing.scalar_one_or_none()
            if report:
                report_id = report.id
                report.status = "generating"
                report.risk_level = overall_risk
                report.risk_score = risk_score
                report.plan_json = plan_json
                report.evidence_json = state.get("evidence_list") or []
                report.dataset_version = state.get("dataset_version")
            else:
                report = Report(
                    id=report_id,
                    profile_id=state.get("profile_id") or None,
                    user_id=state.get("user_id") or None,
                    anonymous_id=state.get("anonymous_id") or None,
                    run_id=run_id,
                    status="generating",
                    risk_level=overall_risk,
                    risk_score=risk_score,
                    plan_json=plan_json,
                    evidence_json=state.get("evidence_list") or [],
                    dataset_version=state.get("dataset_version"),
                    version=state.get("version") or 1,
                    parent_report_id=state.get("parent_report_id") or None,
                )
                db.add(report)
            await db.commit()
            db_saved = True
    except Exception as exc:
        logger.exception("Failed to persist report to DB")
        compliance_issues.append(f"报告保存失败：{exc!s}")

    if not db_saved:
        await _push_sse(run_id, "failed", {
            "message": "报告保存失败，请稍后重试",
        })

    return {
        "report_id": report_id,
        "report_draft": plan_json,
        "compliance_passed": compliance_passed,
        "compliance_issues": compliance_issues,
        "completed_at": datetime.now(UTC).isoformat(),
    }
