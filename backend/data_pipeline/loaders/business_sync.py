"""
把 published_data_records 同步进推荐引擎实际查询的业务表
（admission_scores / rank_segments / admission_plans）。

data_pipeline 的发布区（published_data_records）和业务查询表是刻意分离的两层：
发布区可以任意重跑、回滚、发新版本，不会因为一次采集问题污染业务表；业务表只应该
接收这里显式同步过的干净数据（见 docs/08_jiangsu_data_pipeline_handoff.md §7
P0 第 10 项，这个模块就是补上那道缺失的 loader）。

字段映射说明：
- university_code -> universities.id：published payload 里的 university_code
  是教育部院校代码，需要先解析成 universities 表的内部 id。目标 10 校里有 8 所在
  universities 表里还不存在（现有种子数据是别的省份的 mock），这里按
  configs/jiangsu.yaml 里人工审计过的 code/name 自动创建，985/211/双一流状态按
  公开事实（学校基本信息，不是招生数据本身）手动核对填入 _UNIVERSITY_META，不受
  PRD "不得用推测值补齐招生数据" 约束——如果以后产品侧要调整，直接改这个字典。
- major_category：admission_scores 现有 51 条老种子数据这个字段全是 NULL（代表
  院校整体线）；但 search_admission_sql（app/engine/retrieval.py）允许同一
  university_id/year/batch/subject_type 下出现多行，risk_engine.py 也按
  major_category 做扎堆检测——这个字段本来就设计成可以承载"专业组"粒度。这里填
  major_group_name（如"南京航空航天大学05专业组(化学)"），是 admission_scores
  表目前能承载的最细粒度字段；major_group_code/selection_requirement/campus 等
  字段该表没有对应列，会丢失，这是现有业务表结构的限制，不在这次改动范围内。
- 幂等：admission_scores/admission_plans 都没有能防重复插入的数据库唯一约束，
  这里在应用层按业务自然键先查后写（存在则更新数值字段，不存在则插入），可以重复
  运行不产生重复行。rank_segments 有真正的数据库唯一约束（province/year/
  subject_type/score），upsert 逻辑同样先查后写以保持三者行为一致。
- 覆盖范围：只读 published_data_records，不读 staging_records——数据必须经过
  显式 publish 才能进业务表，这是 staging/发布分离设计的意义所在。当前只有
  AdmissionScoreRecord 类型被真正发布过（2025 年 106 条），RankSegmentRecord/
  AdmissionPlanRecord 还停留在 staging 阶段没有走到发布这一步，所以
  sync_rank_segments/sync_admission_plans 现在会返回 seen=0——这不是 bug，是
  等对应数据集真正发布后这个 loader 自动就能用，不需要改代码。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admission import AdmissionPlan, AdmissionScore, RankSegment, University
from app.models.data_pipeline import PublishedDataRecord

# 目标 10 校里 universities 表原本没有的那 8 所，按公开信息核对的基本信息。
_UNIVERSITY_META: dict[str, dict] = {
    "10284": {"is_985": True, "is_211": True, "is_shuangyiliu": True, "school_type": "综合"},
    "10285": {"is_985": False, "is_211": True, "is_shuangyiliu": True, "school_type": "综合"},
    "10286": {"is_985": True, "is_211": True, "is_shuangyiliu": True, "school_type": "综合"},
    "10287": {"is_985": False, "is_211": True, "is_shuangyiliu": True, "school_type": "理工"},
    "10288": {"is_985": False, "is_211": True, "is_shuangyiliu": True, "school_type": "理工"},
    "10290": {"is_985": False, "is_211": True, "is_shuangyiliu": True, "school_type": "理工"},
    "10294": {"is_985": False, "is_211": True, "is_shuangyiliu": True, "school_type": "理工"},
    "10295": {"is_985": False, "is_211": True, "is_shuangyiliu": True, "school_type": "综合"},
    "10307": {"is_985": False, "is_211": True, "is_shuangyiliu": True, "school_type": "农业"},
    "10316": {"is_985": False, "is_211": True, "is_shuangyiliu": True, "school_type": "医药"},
}


@dataclass
class SyncResult:
    record_type: str
    seen: int = 0
    created: int = 0
    updated: int = 0
    skipped_missing_university: list[str] = field(default_factory=list)


def _get_or_create_university(session: Session, *, code: str, name: str) -> University | None:
    university = session.scalar(select(University).where(University.code == code))
    if university is not None:
        return university
    meta = _UNIVERSITY_META.get(code)
    if meta is None:
        # 白名单之外的院校代码不应该出现在已发布数据里（发布前的白名单校验已经拦过一次），
        # 这里再兜底一次，遇到未知代码宁可跳过也不要凭空建一条缺失基本信息的院校记录。
        return None
    university = University(name=name, code=code, **meta)
    session.add(university)
    session.flush()
    return university


def _published_rows(session: Session, record_type: str) -> list[PublishedDataRecord]:
    return list(
        session.scalars(
            select(PublishedDataRecord).where(PublishedDataRecord.record_type == record_type)
        ).all()
    )


def sync_admission_scores(session: Session) -> SyncResult:
    result = SyncResult(record_type="AdmissionScoreRecord")
    for row in _published_rows(session, "AdmissionScoreRecord"):
        result.seen += 1
        payload = row.payload_json
        university = _get_or_create_university(
            session, code=payload["university_code"], name=payload["university_name"]
        )
        if university is None:
            result.skipped_missing_university.append(payload["university_code"])
            continue

        major_category = payload.get("major_group_name") or payload.get("major_group_code")
        existing = session.scalar(
            select(AdmissionScore).where(
                AdmissionScore.university_id == university.id,
                AdmissionScore.year == payload["year"],
                AdmissionScore.province == payload["province"],
                AdmissionScore.batch == payload["batch"],
                AdmissionScore.subject_type == payload["subject_type"],
                AdmissionScore.major_category == major_category,
            )
        )
        values = dict(
            min_score=payload.get("min_score"),
            min_rank=payload.get("min_rank"),
            avg_score=payload.get("avg_score"),
            max_score=payload.get("max_score"),
            enrollment_count=payload.get("enrollment_count"),
        )
        if existing is None:
            session.add(
                AdmissionScore(
                    university_id=university.id,
                    year=payload["year"],
                    province=payload["province"],
                    batch=payload["batch"],
                    subject_type=payload["subject_type"],
                    major_category=major_category,
                    **values,
                )
            )
            result.created += 1
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            result.updated += 1
    session.flush()
    return result


def sync_rank_segments(session: Session) -> SyncResult:
    result = SyncResult(record_type="RankSegmentRecord")
    for row in _published_rows(session, "RankSegmentRecord"):
        result.seen += 1
        payload = row.payload_json
        existing = session.scalar(
            select(RankSegment).where(
                RankSegment.province == payload["province"],
                RankSegment.year == payload["year"],
                RankSegment.subject_type == payload["subject_type"],
                RankSegment.score == payload["score"],
            )
        )
        if existing is None:
            session.add(
                RankSegment(
                    province=payload["province"],
                    year=payload["year"],
                    subject_type=payload["subject_type"],
                    score=payload["score"],
                    cumulative_rank=payload["cumulative_rank"],
                )
            )
            result.created += 1
        else:
            existing.cumulative_rank = payload["cumulative_rank"]
            result.updated += 1
    session.flush()
    return result


def sync_admission_plans(session: Session) -> SyncResult:
    result = SyncResult(record_type="AdmissionPlanRecord")
    for row in _published_rows(session, "AdmissionPlanRecord"):
        result.seen += 1
        payload = row.payload_json
        university = _get_or_create_university(
            session, code=payload["university_code"], name=payload["university_name"]
        )
        if university is None:
            result.skipped_missing_university.append(payload["university_code"])
            continue

        major_group = payload.get("major_group_code")
        major_code = payload.get("major_code")
        selection = payload.get("selection_requirement")
        existing = session.scalar(
            select(AdmissionPlan).where(
                AdmissionPlan.university_id == university.id,
                AdmissionPlan.year == payload["year"],
                AdmissionPlan.province == payload["province"],
                AdmissionPlan.batch == payload["batch"],
                AdmissionPlan.major_group == major_group,
                AdmissionPlan.major_code == major_code,
            )
        )
        values = dict(
            quota=payload.get("quota"),
            tuition=payload.get("tuition"),
            subjects=None if not selection or selection == "不限" else [selection],
            dataset_version=row.dataset_version_id,
        )
        if existing is None:
            session.add(
                AdmissionPlan(
                    university_id=university.id,
                    year=payload["year"],
                    province=payload["province"],
                    batch=payload["batch"],
                    major_group=major_group,
                    major_code=major_code,
                    **values,
                )
            )
            result.created += 1
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            result.updated += 1
    session.flush()
    return result


def sync_all(session: Session) -> list[SyncResult]:
    """依次同步三张业务表，返回每种 record_type 的同步结果，供 CLI/脚本打印报告。"""
    return [
        sync_admission_scores(session),
        sync_rank_segments(session),
        sync_admission_plans(session),
    ]
