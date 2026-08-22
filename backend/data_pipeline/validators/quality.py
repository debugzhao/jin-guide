from __future__ import annotations

import hashlib
from collections import Counter
from typing import Iterable

from data_pipeline.config import PipelineConfig
from data_pipeline.records import (
    AdmissionPlanRecord,
    AdmissionScoreRecord,
    DocumentChunkRecord,
    PolicyRuleRecord,
    RankSegmentRecord,
    ValidatedRecord,
    ValidationIssue,
)
from data_pipeline.validators.whitelist import WhitelistViolation, require_whitelisted_university


Record = (
    AdmissionPlanRecord
    | AdmissionScoreRecord
    | RankSegmentRecord
    | DocumentChunkRecord
    | PolicyRuleRecord
)


def natural_key(record: Record) -> str:
    if isinstance(record, RankSegmentRecord):
        parts = [record.province, record.year, record.subject_type, record.score]
    elif isinstance(record, DocumentChunkRecord):
        parts = [
            record.province,
            record.year,
            record.document_type,
            record.university_code,
            record.provenance.source_document_id,
            record.chunk_index,
        ]
    elif isinstance(record, PolicyRuleRecord):
        parts = [record.province, record.year, record.batch, record.subject_type, "policy_rule"]
    elif isinstance(record, AdmissionScoreRecord):
        parts = [
            record.province,
            record.year,
            record.batch,
            record.subject_type,
            record.university_code,
            record.major_group_code,
            record.admission_type,
            record.line_type,
        ]
    else:
        # major_group_code/major_code 允许为空（见 records.py::AdmissionPlanRecord 注释），
        # 加 major_name 兜底去重——否则同一学校同批次下所有缺代码的专业会撞成同一个
        # natural_key，被后面的重复校验错误地拒绝。restrictions 也加进来：单校招生
        # 计划页里常见同一专业名称按备注区分成多条独立招生线（如宁波大学"音乐学
        # （师范）"按备注"器乐主项"/"声乐主项"拆成两行、计划数不同），缺 major_code
        # 时备注往往是唯一能把它们分开的字段，已用真实数据验证过这个坑。
        parts = [
            record.province,
            record.year,
            record.batch,
            record.subject_type,
            record.university_code,
            record.major_group_code,
            record.major_code,
            record.major_name,
            record.admission_type,
            record.restrictions,
        ]
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_records(records: Iterable[Record], config: PipelineConfig) -> list[ValidatedRecord]:
    materialized = list(records)
    keys = [natural_key(record) for record in materialized]
    duplicate_keys = {key for key, count in Counter(keys).items() if count > 1}
    results: list[ValidatedRecord] = []

    rank_groups: dict[tuple[int, str], list[RankSegmentRecord]] = {}
    for record in materialized:
        if isinstance(record, RankSegmentRecord):
            rank_groups.setdefault((record.year, record.subject_type), []).append(record)

    monotonic_issues: set[str] = set()
    for group in rank_groups.values():
        ordered = sorted(group, key=lambda item: item.score, reverse=True)
        previous_rank = 0
        for record in ordered:
            if record.cumulative_rank < previous_rank:
                monotonic_issues.add(natural_key(record))
            previous_rank = max(previous_rank, record.cumulative_rank)

    for record, key in zip(materialized, keys, strict=True):
        issues: list[ValidationIssue] = []
        if key in duplicate_keys:
            issues.append(
                ValidationIssue(
                    code="duplicate_natural_key",
                    message="同一来源任务中存在重复业务键",
                    severity="error",
                )
            )
        if key in monotonic_issues:
            issues.append(
                ValidationIssue(
                    code="rank_not_monotonic",
                    message="分数降低时累计位次不应减小",
                    severity="error",
                    field="cumulative_rank",
                )
            )
        if isinstance(record, (AdmissionScoreRecord, AdmissionPlanRecord)):
            try:
                require_whitelisted_university(
                    university_code=record.university_code,
                    university_name=record.university_name,
                    config=config,
                )
            except WhitelistViolation as exc:
                issues.append(
                    ValidationIssue(
                        code="university_not_whitelisted",
                        message=str(exc),
                        severity="error",
                        field="university_code",
                    )
                )
        if isinstance(record, AdmissionScoreRecord) and record.min_rank is None:
            issues.append(
                ValidationIssue(
                    code="min_rank_missing",
                    message="官方投档表未提供最低位次，发布前应使用逐分段表精确关联",
                    severity="warning",
                    field="min_rank",
                )
            )
        if isinstance(record, PolicyRuleRecord):
            if record.volunteer_mode == "unknown":
                issues.append(
                    ValidationIssue(
                        code="volunteer_mode_missing",
                        message="未能从官方正文确定志愿模式",
                        severity="warning",
                        field="volunteer_mode",
                    )
                )
            if record.max_volunteers is None:
                issues.append(
                    ValidationIssue(
                        code="max_volunteers_missing",
                        message="未能从官方正文确定最大志愿数",
                        severity="warning",
                        field="max_volunteers",
                    )
                )

        status = "valid"
        if any(issue.severity == "error" for issue in issues):
            status = "rejected"
        elif issues:
            status = "needs_review"
        results.append(
            ValidatedRecord(
                record_type=record.__class__.__name__,
                natural_key=key,
                status=status,
                payload=record.model_dump(mode="json"),
                issues=issues,
            )
        )
    return results


def attach_min_ranks(
    scores: Iterable[AdmissionScoreRecord],
    rank_segments: Iterable[RankSegmentRecord],
) -> list[AdmissionScoreRecord]:
    lookup = {
        (segment.year, segment.subject_type, segment.score): segment.cumulative_rank
        for segment in rank_segments
    }
    return [
        score.model_copy(
            update={
                "min_rank": lookup.get((score.year, score.subject_type, score.min_score))
            }
        )
        for score in scores
    ]
