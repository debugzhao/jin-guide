"""
学校/分数/选科查询 — 建档前聊天场景（IntakeAgent）专用的确定性查询工具。

高考录取分数是强事实性数据，不能让 LLM 凭参数记忆回答，必须经这里的纯 SQL 查询
拿到真实数据后再交给模型组织语言（CLAUDE.md「确定性系统给结论，Agent 给解释」的延伸）。
只做结构化数据对比，不掺杂培养方向/师资这类定性内容（那部分交给 vector_search）。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.tool_response import ToolResponse
from app.models.admission import AdmissionScore, SubjectRequirement, University


def _find_university(db: Session, name: str) -> University | None:
    stmt = select(University).where(University.name.ilike(f"%{name}%")).limit(1)
    return db.execute(stmt).scalars().first()


def lookup_university_score(
    db: Session,
    university_name: str,
    province: str,
    batch: str = "本科批",
    year: int | None = None,
) -> ToolResponse:
    """查某高校在某省份的历年录取分数/位次（不传 year 时返回全部已有年份，按年份倒序）。"""
    university = _find_university(db, university_name)
    if university is None:
        return ToolResponse.error("UNIVERSITY_NOT_FOUND", f"未找到院校「{university_name}」", {})

    stmt = select(AdmissionScore).where(
        AdmissionScore.university_id == university.id,
        AdmissionScore.province == province,
        AdmissionScore.batch == batch,
    )
    if year is not None:
        stmt = stmt.where(AdmissionScore.year == year)
    stmt = stmt.order_by(AdmissionScore.year.desc())

    rows = db.execute(stmt).scalars().all()
    if not rows:
        return ToolResponse.partial(
            text=f"{university.name} 在 {province}{batch} 暂无录取分数记录",
            data={"university_name": university.name, "records": []},
        )

    records = [
        {
            "year": r.year,
            "subject_type": r.subject_type,
            "min_score": r.min_score,
            "min_rank": r.min_rank,
            "avg_score": r.avg_score,
            "avg_rank": r.avg_rank,
            "max_score": r.max_score,
        }
        for r in rows
    ]
    return ToolResponse.success(
        text=f"{university.name} 在 {province}{batch} 共 {len(records)} 条录取记录",
        data={
            "university_name": university.name,
            "city": university.city,
            "is_985": university.is_985,
            "is_211": university.is_211,
            "records": records,
        },
    )


def lookup_subject_requirement(
    db: Session,
    university_name: str,
    major_name: str | None = None,
) -> ToolResponse:
    """查某高校（可选：某专业）的选科要求和体检限制。"""
    university = _find_university(db, university_name)
    if university is None:
        return ToolResponse.error("UNIVERSITY_NOT_FOUND", f"未找到院校「{university_name}」", {})

    stmt = select(SubjectRequirement).where(SubjectRequirement.university_id == university.id)
    if major_name:
        stmt = stmt.where(SubjectRequirement.major_name.ilike(f"%{major_name}%"))
    stmt = stmt.limit(20)

    rows = db.execute(stmt).scalars().all()
    if not rows:
        suffix = f"「{major_name}」专业的" if major_name else ""
        return ToolResponse.partial(
            text=f"{university.name} 暂无{suffix}选科要求记录",
            data={"university_name": university.name, "requirements": []},
        )

    requirements = [
        {
            "major_name": r.major_name,
            "required_subjects": r.required_subjects or [],
            "optional_subjects": r.optional_subjects or [],
            "optional_required_count": r.optional_required_count,
            "restricted_subjects": r.restricted_subjects or [],
            "medical_restrictions": r.medical_restrictions or {},
        }
        for r in rows
    ]
    return ToolResponse.success(
        text=f"{university.name} 共 {len(requirements)} 条选科要求记录",
        data={"university_name": university.name, "requirements": requirements},
    )


def compare_universities(
    db: Session,
    university_names: list[str],
    province: str,
    batch: str = "本科批",
) -> ToolResponse:
    """多所高校在同一省份的录取分数/位次/选科要求并排对比，只出结构化数据不做定性描述。"""
    results = []
    not_found = []

    for name in university_names:
        university = _find_university(db, name)
        if university is None:
            not_found.append(name)
            continue

        latest = db.execute(
            select(AdmissionScore)
            .where(
                AdmissionScore.university_id == university.id,
                AdmissionScore.province == province,
                AdmissionScore.batch == batch,
            )
            .order_by(AdmissionScore.year.desc())
            .limit(1)
        ).scalars().first()

        subject_req = db.execute(
            select(SubjectRequirement)
            .where(SubjectRequirement.university_id == university.id)
            .limit(1)
        ).scalars().first()

        results.append(
            {
                "university_name": university.name,
                "city": university.city,
                "is_985": university.is_985,
                "is_211": university.is_211,
                "year": latest.year if latest else None,
                "min_score": latest.min_score if latest else None,
                "min_rank": latest.min_rank if latest else None,
                "required_subjects": (subject_req.required_subjects or []) if subject_req else [],
            }
        )

    if not results:
        return ToolResponse.error(
            "NO_UNIVERSITY_FOUND", f"未找到院校：{'、'.join(not_found)}", {}
        )

    status_text = f"对比 {len(results)} 所院校在 {province}{batch} 的数据"
    data = {"universities": results, "not_found": not_found}
    if not_found:
        status_text += f"；未找到：{'、'.join(not_found)}"
        return ToolResponse.partial(text=status_text, data=data)
    return ToolResponse.success(text=status_text, data=data)
