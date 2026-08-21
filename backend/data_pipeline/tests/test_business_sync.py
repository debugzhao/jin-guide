from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.admission import AdmissionPlan, AdmissionScore, RankSegment, University
from app.models.base import Base
from app.models.data_pipeline import DatasetVersion, PublishedDataRecord
from data_pipeline.loaders.business_sync import (
    sync_admission_plans,
    sync_admission_scores,
    sync_rank_segments,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            University.__table__,
            AdmissionScore.__table__,
            RankSegment.__table__,
            AdmissionPlan.__table__,
            DatasetVersion.__table__,
            PublishedDataRecord.__table__,
        ],
    )
    with Session(engine) as db:
        yield db


def _dataset_version(session, *, dataset_type="admission", year=2025) -> DatasetVersion:
    version = DatasetVersion(
        name=f"jiangsu_top10_{year}_{dataset_type}_v1",
        dataset_type=dataset_type,
        province="江苏",
        year=year,
        version=1,
        status="published",
        record_count=1,
    )
    session.add(version)
    session.flush()
    return version


def _published(session, dataset_version, *, record_type, natural_key, payload) -> PublishedDataRecord:
    row = PublishedDataRecord(
        dataset_version_id=dataset_version.id,
        record_type=record_type,
        natural_key=natural_key,
        province=payload.get("province", "江苏"),
        year=payload["year"],
        subject_type=payload.get("subject_type"),
        batch=payload.get("batch"),
        university_code=payload.get("university_code"),
        major_group_code=payload.get("major_group_code"),
        major_code=payload.get("major_code"),
        payload_json=payload,
        provenance_json={},
    )
    session.add(row)
    session.flush()
    return row


def _score_payload(**overrides) -> dict:
    payload = {
        "province": "江苏",
        "year": 2025,
        "batch": "本科批",
        "subject_type": "physics",
        "university_code": "10287",
        "university_name": "南京航空航天大学",
        "major_group_code": "05",
        "major_group_name": "南京航空航天大学05专业组(化学)",
        "min_score": 649,
        "min_rank": 4675,
        "avg_score": None,
        "max_score": None,
        "enrollment_count": None,
    }
    payload.update(overrides)
    return payload


def test_sync_admission_scores_creates_missing_university_and_score_row(session) -> None:
    version = _dataset_version(session)
    _published(session, version, record_type="AdmissionScoreRecord", natural_key="k1", payload=_score_payload())

    result = sync_admission_scores(session)

    assert result.seen == 1
    assert result.created == 1
    assert result.skipped_missing_university == []

    university = session.scalar(select(University).where(University.code == "10287"))
    assert university is not None
    assert university.is_211 is True

    score = session.scalar(select(AdmissionScore).where(AdmissionScore.university_id == university.id))
    assert score.min_score == 649
    assert score.min_rank == 4675
    assert score.major_category == "南京航空航天大学05专业组(化学)"


def test_sync_admission_scores_is_idempotent_and_updates_on_rerun(session) -> None:
    version = _dataset_version(session)
    _published(session, version, record_type="AdmissionScoreRecord", natural_key="k1", payload=_score_payload())
    sync_admission_scores(session)

    # 同一条自然键的数据被重新发布（例如补充了 min_rank），natural_key 不同但业务键相同
    _published(
        session, version, record_type="AdmissionScoreRecord", natural_key="k2",
        payload=_score_payload(min_rank=5000),
    )
    result = sync_admission_scores(session)

    assert result.seen == 2
    assert result.created == 0
    assert result.updated == 2
    rows = session.scalars(select(AdmissionScore)).all()
    assert len(rows) == 1  # 没有产生重复行
    assert rows[0].min_rank == 5000  # 后写覆盖


def test_sync_admission_scores_skips_unknown_university_code(session) -> None:
    version = _dataset_version(session)
    _published(
        session, version, record_type="AdmissionScoreRecord", natural_key="k1",
        payload=_score_payload(university_code="99999", university_name="未知高校"),
    )

    result = sync_admission_scores(session)

    assert result.seen == 1
    assert result.created == 0
    assert result.skipped_missing_university == ["99999"]
    assert session.scalar(select(University).where(University.code == "99999")) is None


def test_sync_rank_segments_upserts_on_unique_key(session) -> None:
    version = _dataset_version(session, dataset_type="rank_segment")
    payload = {"province": "江苏", "year": 2025, "subject_type": "physics", "score": 661, "cumulative_rank": 728}
    _published(session, version, record_type="RankSegmentRecord", natural_key="r1", payload=payload)

    result = sync_rank_segments(session)
    assert result.created == 1

    payload2 = {**payload, "cumulative_rank": 730}
    _published(session, version, record_type="RankSegmentRecord", natural_key="r2", payload=payload2)
    result2 = sync_rank_segments(session)

    # 每次都是全量重扫 published_data_records，r1 和 r2 都落在同一个业务自然键上，
    # 所以这一轮两条都是 update，不是只有新增的 r2 才算——这正是"可重复运行不产生
    # 重复行"的幂等设计，行数应该始终只有 1。
    assert result2.seen == 2
    assert result2.updated == 2
    rows = session.scalars(select(RankSegment)).all()
    assert len(rows) == 1
    assert rows[0].cumulative_rank == 730


def test_sync_admission_plans_maps_selection_requirement_to_subjects(session) -> None:
    version = _dataset_version(session, dataset_type="plan")
    payload = {
        "province": "江苏",
        "year": 2025,
        "batch": "本科批",
        "subject_type": "physics",
        "university_code": "10284",
        "university_name": "南京大学",
        "major_group_code": "07",
        "major_code": "070101",
        "major_name": "数学与应用数学",
        "quota": 30,
        "tuition": 5800,
        "selection_requirement": "物理",
    }
    _published(session, version, record_type="AdmissionPlanRecord", natural_key="p1", payload=payload)

    result = sync_admission_plans(session)

    assert result.created == 1
    plan = session.scalar(select(AdmissionPlan))
    assert plan.quota == 30
    assert plan.subjects == ["物理"]


def test_sync_admission_plans_treats_unrestricted_as_no_subjects(session) -> None:
    version = _dataset_version(session, dataset_type="plan")
    payload = {
        "province": "江苏",
        "year": 2025,
        "batch": "本科批",
        "subject_type": "history",
        "university_code": "10284",
        "university_name": "南京大学",
        "major_group_code": "01",
        "major_code": "030101",
        "major_name": "法学",
        "quota": 20,
        "tuition": 5800,
        "selection_requirement": "不限",
    }
    _published(session, version, record_type="AdmissionPlanRecord", natural_key="p1", payload=payload)

    sync_admission_plans(session)

    plan = session.scalar(select(AdmissionPlan))
    assert plan.subjects is None
