from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.data_pipeline import (
    CollectionRun,
    DataSource,
    DatasetVersion,
    PublishedDataRecord,
    SourceDocument,
    StagingRecord,
)
from data_pipeline.config import load_pipeline_config
from data_pipeline.loaders import PipelineRepository, apply_admission_score_enrichment
from data_pipeline.raw_store import StoredArtifact
from data_pipeline.records import AdmissionScoreRecord, Provenance, RankSegmentRecord
from data_pipeline.validators import validate_records


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            DataSource.__table__,
            CollectionRun.__table__,
            SourceDocument.__table__,
            StagingRecord.__table__,
            DatasetVersion.__table__,
            PublishedDataRecord.__table__,
        ],
    )
    with Session(engine) as db:
        yield db


def _provenance(source_title: str) -> Provenance:
    return Provenance(
        source_url="https://www.jseea.cn/file.pdf",
        source_document_id="placeholder",
        source_title=source_title,
        year=2025,
        authority_level="official",
        collected_at=datetime.now(UTC).isoformat(),
        parser_version="v1",
    )


def _artifact(tmp_path, name: str) -> StoredArtifact:
    content_path = tmp_path / f"{name}.pdf"
    metadata_path = tmp_path / f"{name}.metadata.json"
    content_path.write_bytes(name.encode())
    metadata_path.write_text("{}", encoding="utf-8")
    return StoredArtifact(
        source_id="jseea-admission-score-2025",
        source_url=f"https://www.jseea.cn/{name}.pdf",
        checksum=name.ljust(64, "0"),
        content_path=content_path,
        metadata_path=metadata_path,
        collected_at=datetime.now(UTC).isoformat(),
        changed=True,
        size_bytes=8,
    )


def _stage(session, repository, run, tmp_path, name, records, config):
    document, _ = repository.register_document(
        run=run, source=_source(config), artifact=_artifact(tmp_path, name), title=name
    )
    return repository.stage_records(
        run=run, document=document, records=validate_records(records, config)
    )


def _source(config):
    return next(item for item in config.sources if item.id == "jseea-admission-score-2025")


def test_enrichment_fills_min_rank_from_matching_rank_segment(session, tmp_path) -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    repository = PipelineRepository(session)
    repository.sync_sources(config)
    run = repository.start_run("jseea-admission-score-2025")

    score = AdmissionScoreRecord(
        province="江苏",
        year=2025,
        batch="本科批",
        subject_type="physics",
        university_code="10284",
        university_name="南京大学",
        major_group_code="07",
        min_score=661,
        min_rank=None,
        provenance=_provenance("投档线"),
    )
    rank = RankSegmentRecord(province="江苏", year=2025, subject_type="physics", score=661, cumulative_rank=728, provenance=_provenance("逐分段表"))
    _stage(session, repository, run, tmp_path, "score", [score], config)
    _stage(session, repository, run, tmp_path, "rank", [rank], config)

    summary = apply_admission_score_enrichment(session, config=config, year=2025)

    assert summary["valid"] == 1
    assert summary["needs_review"] == 0
    row = session.scalars(select(StagingRecord).where(StagingRecord.record_type == "AdmissionScoreRecord")).one()
    assert row.payload_json["min_rank"] == 728
    assert row.review_status == "valid"


def test_enrichment_applies_manual_override_and_stamps_reviewer(session, tmp_path) -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    repository = PipelineRepository(session)
    repository.sync_sources(config)
    run = repository.start_run("jseea-admission-score-2025")

    score = AdmissionScoreRecord(
        province="江苏",
        year=2025,
        batch="本科批",
        subject_type="physics",
        university_code="10286",
        university_name="东南大学",
        major_group_code="08",
        min_score=644,
        min_rank=None,
        provenance=_provenance("投档线"),
    )
    _stage(session, repository, run, tmp_path, "score", [score], config)

    summary = apply_admission_score_enrichment(
        session,
        config=config,
        year=2025,
        manual_rank_overrides={("physics", 644): 6362},
        reviewer="claude-code:image-verified",
    )

    assert summary["manually_verified"] == 1
    assert summary["valid"] == 1
    row = session.scalars(select(StagingRecord).where(StagingRecord.record_type == "AdmissionScoreRecord")).one()
    assert row.payload_json["min_rank"] == 6362
    assert row.review_status == "valid"
    assert row.reviewed_by == "claude-code:image-verified"
    assert row.reviewed_at is not None


def test_enrichment_leaves_unmatched_score_as_needs_review(session, tmp_path) -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    repository = PipelineRepository(session)
    repository.sync_sources(config)
    run = repository.start_run("jseea-admission-score-2025")

    score = AdmissionScoreRecord(
        province="江苏",
        year=2025,
        batch="本科批",
        subject_type="physics",
        university_code="10284",
        university_name="南京大学",
        major_group_code="07",
        min_score=661,
        min_rank=None,
        provenance=_provenance("投档线"),
    )
    _stage(session, repository, run, tmp_path, "score", [score], config)

    summary = apply_admission_score_enrichment(session, config=config, year=2025)

    assert summary["needs_review"] == 1
    row = session.scalars(select(StagingRecord).where(StagingRecord.record_type == "AdmissionScoreRecord")).one()
    assert row.payload_json["min_rank"] is None
    assert row.review_status == "needs_review"
    assert row.reviewed_by is None
