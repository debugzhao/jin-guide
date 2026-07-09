"""
招生数据模型：院校、录取分数线、位次段、选科要求
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class University(Base):
    __tablename__ = "universities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)         # 教育部院校代码
    city: Mapped[str | None] = mapped_column(String(50), nullable=True)
    province: Mapped[str | None] = mapped_column(String(50), nullable=True)     # 学校所在省份
    school_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 综合/理工/师范/医科/财经/农业/军事
    is_985: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_211: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_shuangyiliu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_medical_program: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    annual_tuition_min: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 元/年
    annual_tuition_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    admission_scores: Mapped[list["AdmissionScore"]] = relationship(back_populates="university")
    subject_requirements: Mapped[list["SubjectRequirement"]] = relationship(back_populates="university")

    __table_args__ = (
        Index("ix_universities_name", "name"),
    )


class AdmissionScore(Base):
    """历年录取分数线（按年、省份、批次、科类）"""
    __tablename__ = "admission_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    university_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("universities.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    province: Mapped[str] = mapped_column(String(50), nullable=False)      # 招生省份
    batch: Mapped[str] = mapped_column(String(50), nullable=False)          # 本科批/专科批/提前批
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)   # physics/history
    major_category: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 专业大类（NULL=全校）
    min_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enrollment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    university: Mapped["University"] = relationship(back_populates="admission_scores")

    __table_args__ = (
        Index("ix_admission_scores_lookup", "province", "year", "batch", "subject_type"),
        Index("ix_admission_scores_university", "university_id"),
    )


class RankSegment(Base):
    """省份位次段表（分数 → 累计位次）"""
    __tablename__ = "rank_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    province: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)  # physics/history
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_rank: Mapped[int] = mapped_column(Integer, nullable=False)   # 该分数的累计位次（全省排名）

    __table_args__ = (
        Index("ix_rank_segments_lookup", "province", "year", "subject_type", "score", unique=True),
    )


class SubjectRequirement(Base):
    """选科要求（高校专业对高考选科的限制）"""
    __tablename__ = "subject_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    university_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("universities.id", ondelete="CASCADE"), nullable=False
    )
    major_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # required_subjects: ["物理"] 表示必须选物理; [] 表示不限
    required_subjects: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # optional_required: 从 optional_subjects 中至少选 N 门
    optional_subjects: Mapped[list | None] = mapped_column(JSON, nullable=True)
    optional_required_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # restricted_subjects: 有此选科则不可报 (极少见)
    restricted_subjects: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # medical_restrictions: 体检受限说明 (JSON: {"color_blind": "不招", "height_min": 155})
    medical_restrictions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    university: Mapped["University"] = relationship(back_populates="subject_requirements")

    __table_args__ = (
        Index("ix_subject_req_university", "university_id"),
        Index("ix_subject_req_major", "university_id", "major_name"),
    )


class ProvinceThreshold(Base):
    """省份级冲稳保位次阈值 + 志愿数上限配置，替代代码内硬编码 (docs/03_data_model.md §2.5)"""
    __tablename__ = "province_thresholds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    province: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    high_rush_rank_gap: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    rush_rank_gap_min: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    rush_rank_gap_max: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    target_rank_gap: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    safe_rank_gap: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    max_volunteers: Mapped[int] = mapped_column(Integer, nullable=False, default=96)

    __table_args__ = (
        Index("ix_province_thresholds_province_year", "province", "year", unique=True),
    )
