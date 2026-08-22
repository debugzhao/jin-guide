from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# "unified" 用于浙江等"3+3不分文理"省份——考生不区分物理类/历史类，志愿也不按科类分批次
SubjectType = Literal["physics", "history", "unified"]
ReviewStatus = Literal["valid", "needs_review", "rejected"]


class Provenance(BaseModel):
    source_url: str
    source_document_id: str
    source_title: str
    year: int
    authority_level: str
    collected_at: str
    parser_version: str
    dataset_version: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    table_row: int | None = Field(default=None, ge=1)


class RankSegmentRecord(BaseModel):
    province: str  # 必须显式传入，不设默认值（历史"江苏"默认值曾致解析器静默写错省份）
    year: int
    subject_type: SubjectType
    score: int = Field(ge=0, le=750)
    cumulative_rank: int = Field(gt=0, le=2_000_000)
    provenance: Provenance


class AdmissionScoreRecord(BaseModel):
    province: str  # 必须显式传入，不设默认值（历史"江苏"默认值曾致解析器静默写错省份）
    year: int
    batch: str
    subject_type: SubjectType
    university_code: str
    university_name: str
    provincial_university_code: str | None = None
    major_group_code: str
    major_group_name: str | None = None
    selection_requirement: str | None = None
    admission_type: str = "普通"
    campus: str | None = None
    line_type: Literal["regular", "solicitation"] = "regular"
    min_score: int = Field(ge=0, le=750)
    min_rank: int | None = Field(default=None, gt=0, le=2_000_000)
    avg_score: int | None = Field(default=None, ge=0, le=750)
    max_score: int | None = Field(default=None, ge=0, le=750)
    enrollment_count: int | None = Field(default=None, ge=0, le=100_000)
    provenance: Provenance


class AdmissionPlanRecord(BaseModel):
    province: str  # 必须显式传入，不设默认值（历史"江苏"默认值曾致解析器静默写错省份）
    year: int
    batch: str
    subject_type: SubjectType
    university_code: str
    university_name: str
    provincial_university_code: str | None = None
    # 官方专业组/专业代码只有省考试院发布的正式招生计划文件才带；本校招生网自己的
    # "招生计划"页面通常只列"专业名称+计划数"，不重复展示考试院分配的编号——留空
    # 而不是编造假代码，缺失数据必须明确标记（PRD 硬性要求）。
    major_group_code: str | None = None
    major_code: str | None = None
    major_name: str
    quota: int = Field(gt=0, le=100_000)
    tuition: int | None = Field(default=None, ge=0, le=1_000_000)
    duration_years: int | None = Field(default=None, ge=1, le=8)
    campus: str | None = None
    selection_requirement: str | None = None
    admission_type: str = "普通"
    restrictions: str | None = None
    provenance: Provenance


class DocumentChunkRecord(BaseModel):
    province: str  # 必须显式传入，不设默认值（历史"江苏"默认值曾致解析器静默写错省份）
    year: int
    document_type: Literal["policy", "charter", "major_intro", "transfer_policy"]
    university_code: str | None = None
    section_title: str | None = None
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    provenance: Provenance


class PolicyRuleRecord(BaseModel):
    province: str  # 必须显式传入，不设默认值（历史"江苏"默认值曾致解析器静默写错省份）
    year: int
    batch: str = "普通类本科批"
    subject_type: SubjectType | None = None
    volunteer_mode: Literal["parallel", "sequential", "mixed", "unknown"] = "unknown"
    max_volunteers: int | None = Field(default=None, gt=0, le=200)
    adjustment_allowed: bool | None = None
    adjustment_scope: str | None = None
    filing_rule: str | None = None
    tie_break_rule: str | None = None
    control_score: int | None = Field(default=None, ge=0, le=750)
    provenance: Provenance


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error"]
    field: str | None = None


class ValidatedRecord(BaseModel):
    record_type: str
    natural_key: str
    status: ReviewStatus
    payload: dict
    issues: list[ValidationIssue] = Field(default_factory=list)
