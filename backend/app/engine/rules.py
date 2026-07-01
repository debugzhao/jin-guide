"""
规则引擎：确定性志愿校验函数。
规则引擎给结论，LLM 给解释（PRD 设计约束）。
所有函数返回 ToolResponse，不抛出异常。
"""
from __future__ import annotations

from typing import Any
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from app.agent.tool_response import ToolResponse
from app.models.admission import University, AdmissionScore, SubjectRequirement


# ── 常量 ──────────────────────────────────────────────────────────────────────

BATCH_ORDER = ["提前批", "本科批", "专科批"]  # 高到低

# 必须选但未选的科目阻断报名
_SUBJECT_NAMES = {"物理", "化学", "生物", "历史", "政治", "地理"}


# ── 1. 选科资格校验 ────────────────────────────────────────────────────────────

def check_subject_req(
    university_id: str,
    major_name: str,
    student_subjects: list[str],
    db: Session,
) -> ToolResponse:
    """
    校验考生选科是否满足目标专业的选科要求。

    student_subjects: 已选的科目列表，例如 ["物理", "化学", "地理"]
    返回:
        SUCCESS — 满足要求
        ERROR   — 必选科目缺失（硬阻断）
        PARTIAL — 选科要求数据缺失，降级为未知风险
    """
    ctx = {"university_id": university_id, "major_name": major_name,
           "student_subjects": student_subjects}

    req: SubjectRequirement | None = db.execute(
        select(SubjectRequirement).where(
            SubjectRequirement.university_id == university_id,
            SubjectRequirement.major_name == major_name,
        )
    ).scalar_one_or_none()

    if req is None:
        return ToolResponse.partial(
            text=f'未找到【{major_name}】的选科要求数据，跳过选科校验',
            data={"eligible": None, "reason": "no_data"},
            context=ctx,
        )

    student_set = set(student_subjects)

    # 检查必选科目
    required: list[str] = req.required_subjects or []
    missing_required = [s for s in required if s not in student_set]
    if missing_required:
        return ToolResponse.error(
            code="SUBJECT_REQUIRED_MISSING",
            message=f'报考【{major_name}】必须选修：{"/".join(missing_required)}，考生未选',
            data={"eligible": False, "missing": missing_required},
            context=ctx,
        )

    # 检查可选必选（N 选 M）
    optional: list[str] = req.optional_subjects or []
    opt_count: int = req.optional_required_count or 0
    if optional and opt_count > 0:
        matched_optional = [s for s in optional if s in student_set]
        if len(matched_optional) < opt_count:
            return ToolResponse.error(
                code="SUBJECT_OPTIONAL_INSUFFICIENT",
                message=(
                    f'报考【{major_name}】需要从 {"/".join(optional)} 中至少选 {opt_count} 门，'
                    f'考生仅选了 {len(matched_optional)} 门'
                ),
                data={"eligible": False, "matched": matched_optional, "required_count": opt_count},
                context=ctx,
            )

    return ToolResponse.success(
        text=f'考生选科满足【{major_name}】的选科要求',
        data={"eligible": True},
        context=ctx,
    )


# ── 2. 体检限制校验 ───────────────────────────────────────────────────────────

def check_medical_restriction(
    university_id: str,
    major_name: str,
    has_color_blind: bool,
    height_cm: int | None,
    has_hearing_impairment: bool,
    db: Session,
) -> ToolResponse:
    """
    校验考生身体状况是否满足报考限制。

    返回:
        SUCCESS — 无限制或限制不适用
        ERROR   — 硬阻断（如色盲禁报医科）
        PARTIAL — 无体检限制数据，降级
    """
    ctx = {
        "university_id": university_id,
        "major_name": major_name,
        "has_color_blind": has_color_blind,
        "height_cm": height_cm,
        "has_hearing_impairment": has_hearing_impairment,
    }

    req: SubjectRequirement | None = db.execute(
        select(SubjectRequirement).where(
            SubjectRequirement.university_id == university_id,
            SubjectRequirement.major_name == major_name,
        )
    ).scalar_one_or_none()

    if req is None or not req.medical_restrictions:
        return ToolResponse.success(
            text="无体检限制数据或该专业无体检特殊限制",
            data={"eligible": True, "reason": "no_restriction"},
            context=ctx,
        )

    restrictions: dict[str, Any] = req.medical_restrictions
    violations: list[str] = []

    if has_color_blind and restrictions.get("color_blind") == "不招":
        violations.append("色觉异常（色盲/色弱）不招")

    if has_hearing_impairment and restrictions.get("total_deafness") == "不招":
        violations.append("听力障碍不招")

    min_height = restrictions.get("height_min")
    if min_height and height_cm is not None and height_cm < min_height:
        violations.append(f"身高要求 ≥{min_height}cm，考生 {height_cm}cm 不达标")

    if violations:
        return ToolResponse.error(
            code="MEDICAL_RESTRICTION_BLOCKED",
            message=f'报考【{major_name}】存在体检限制：{"；".join(violations)}',
            data={"eligible": False, "violations": violations},
            context=ctx,
        )

    return ToolResponse.success(
        text=f'考生身体条件满足【{major_name}】的体检要求',
        data={"eligible": True},
        context=ctx,
    )


# ── 3. 批次资格校验 ───────────────────────────────────────────────────────────

def check_batch_eligibility(
    student_rank: int,
    province: str,
    target_batch: str,
    year: int,
    subject_type: str,
    db: Session,
) -> ToolResponse:
    """
    校验考生位次是否具备目标批次报考资格。
    通过查询历年该批次最低录取位次来判断。

    返回:
        SUCCESS — 位次满足批次门槛
        ERROR   — 位次明显低于批次最低录取线
        PARTIAL — 无历史数据，降级
    """
    ctx = {
        "student_rank": student_rank,
        "province": province,
        "target_batch": target_batch,
        "year": year,
        "subject_type": subject_type,
    }

    # 查询该批次最高录取位次（最宽松的学校），作为批次入线门槛
    row = db.execute(
        select(func.max(AdmissionScore.min_rank)).where(
            AdmissionScore.province == province,
            AdmissionScore.year == year,
            AdmissionScore.batch == target_batch,
            AdmissionScore.subject_type == subject_type,
        )
    ).scalar_one_or_none()

    if row is None:
        return ToolResponse.partial(
            text=f"未找到 {province} {year} 年 {target_batch} {subject_type} 类数据，跳过批次校验",
            data={"eligible": None, "reason": "no_data"},
            context=ctx,
        )

    batch_cutoff_rank: int = row
    if student_rank > batch_cutoff_rank:
        return ToolResponse.error(
            code="BATCH_INELIGIBLE",
            message=(
                f"考生位次 {student_rank} 超出 {year} 年 {province} {target_batch} "
                f"最低录取位次 {batch_cutoff_rank}，不具备该批次报考资格"
            ),
            data={
                "eligible": False,
                "student_rank": student_rank,
                "batch_cutoff_rank": batch_cutoff_rank,
            },
            context=ctx,
        )

    return ToolResponse.success(
        text=f"考生位次 {student_rank} 满足 {target_batch} 批次资格（批次最低位次 {batch_cutoff_rank}）",
        data={
            "eligible": True,
            "student_rank": student_rank,
            "batch_cutoff_rank": batch_cutoff_rank,
        },
        context=ctx,
    )


# ── 4. 学费预算校验 ────────────────────────────────────────────────────────────

def check_budget(
    university_id: str,
    family_budget_per_year: int,
    db: Session,
) -> ToolResponse:
    """
    校验学费是否在家庭预算范围内。
    family_budget_per_year: 家庭每年可承受学费上限（元）

    返回:
        SUCCESS — 学费在预算内
        ERROR   — 学费超出预算 30% 以上（硬阻断阈值）
        PARTIAL — 学费数据缺失
    """
    ctx = {
        "university_id": university_id,
        "family_budget_per_year": family_budget_per_year,
    }

    univ: University | None = db.get(University, university_id)

    if univ is None:
        return ToolResponse.partial(
            text="未找到该院校信息，跳过学费校验",
            data={"within_budget": None, "reason": "no_data"},
            context=ctx,
        )

    tuition_min = univ.annual_tuition_min
    tuition_max = univ.annual_tuition_max

    if tuition_min is None:
        return ToolResponse.partial(
            text=f"{univ.name} 暂无学费数据，跳过学费校验",
            data={"within_budget": None, "reason": "no_tuition_data"},
            context=ctx,
        )

    # 以最高档学费作为悲观估算
    tuition_check = tuition_max or tuition_min

    # 超出预算 30% 以上为硬阻断
    if tuition_check > family_budget_per_year * 1.3:
        return ToolResponse.error(
            code="BUDGET_EXCEEDED",
            message=(
                f"{univ.name} 学费最高 {tuition_check:,} 元/年，"
                f"超出家庭预算 {family_budget_per_year:,} 元/年 的 30% 阈值"
            ),
            data={
                "within_budget": False,
                "tuition_max": tuition_check,
                "family_budget": family_budget_per_year,
                "excess_ratio": round(tuition_check / family_budget_per_year - 1, 2),
            },
            context=ctx,
        )

    # 超出预算但在 30% 以内 → 降级告警
    if tuition_check > family_budget_per_year:
        return ToolResponse.partial(
            text=(
                f"{univ.name} 学费 {tuition_check:,} 元/年 略超预算 {family_budget_per_year:,} 元/年，"
                "建议核实家庭可承受能力"
            ),
            data={
                "within_budget": False,
                "tuition_max": tuition_check,
                "family_budget": family_budget_per_year,
                "excess_ratio": round(tuition_check / family_budget_per_year - 1, 2),
            },
            context=ctx,
        )

    return ToolResponse.success(
        text=f"{univ.name} 学费 {tuition_check:,} 元/年，在家庭预算范围内",
        data={
            "within_budget": True,
            "tuition_max": tuition_check,
            "family_budget": family_budget_per_year,
        },
        context=ctx,
    )
