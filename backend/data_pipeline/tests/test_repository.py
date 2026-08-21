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
from data_pipeline.loaders import PipelineRepository, PublicationError
from data_pipeline.raw_store import StoredArtifact
from data_pipeline.records import AdmissionScoreRecord, Provenance
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


def _artifact(tmp_path, *, name: str = "file", checksum: str = "a" * 64) -> StoredArtifact:
    content_path = tmp_path / f"{name}.pdf"
    metadata_path = tmp_path / f"{name}.metadata.json"
    content_path.write_bytes(b"official")
    metadata_path.write_text("{}", encoding="utf-8")
    return StoredArtifact(
        source_id="jseea-admission-score-2025",
        source_url=f"https://www.jseea.cn/{name}.pdf",
        checksum=checksum,
        content_path=content_path,
        metadata_path=metadata_path,
        collected_at=datetime.now(UTC).isoformat(),
        changed=True,
        size_bytes=8,
    )


def _score() -> AdmissionScoreRecord:
    return AdmissionScoreRecord(
        year=2025,
        batch="本科批",
        subject_type="physics",
        university_code="10284",
        university_name="南京大学",
        major_group_code="07",
        min_score=661,
        min_rank=1000,
        provenance=Provenance(
            source_url="https://www.jseea.cn/file.pdf",
            source_document_id="placeholder",
            source_title="投档线",
            year=2025,
            authority_level="official",
            collected_at=datetime.now(UTC).isoformat(),
            parser_version="v1",
        ),
    )


def test_repository_is_idempotent_and_publishes_immutable_version(session, tmp_path) -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    source = next(item for item in config.sources if item.id == "jseea-admission-score-2025")
    repository = PipelineRepository(session)
    repository.sync_sources(config)
    run = repository.start_run(source.id)
    document, created = repository.register_document(
        run=run, source=source, artifact=_artifact(tmp_path), title="投档线"
    )
    duplicate, duplicate_created = repository.register_document(
        run=run, source=source, artifact=_artifact(tmp_path), title="投档线"
    )
    assert created is True
    assert duplicate_created is False
    assert duplicate.id == document.id

    validated = validate_records([_score()], config)
    staged = repository.stage_records(run=run, document=document, records=validated)
    repository.finish_run(run)
    dataset = repository.publish(
        dataset_type="admission", province="江苏", year=2025, staging_records=staged
    )
    assert dataset.name == "jiangsu_top10_2025_admission_v1"
    assert dataset.status == "published"
    published = session.scalars(select(PublishedDataRecord)).all()
    assert len(published) == 1
    assert published[0].university_code == "10284"


def test_repository_blocks_unreviewed_records(session, tmp_path) -> None:
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    source = next(item for item in config.sources if item.id == "jseea-admission-score-2025")
    repository = PipelineRepository(session)
    repository.sync_sources(config)
    run = repository.start_run(source.id)
    document, _ = repository.register_document(
        run=run, source=source, artifact=_artifact(tmp_path), title="投档线"
    )
    score = _score().model_copy(update={"min_rank": None})
    staged = repository.stage_records(
        run=run, document=document, records=validate_records([score], config)
    )
    with pytest.raises(PublicationError, match="require review"):
        repository.publish(
            dataset_type="admission", province="江苏", year=2025, staging_records=staged
        )


def test_repository_rejects_duplicate_natural_key_across_documents(session, tmp_path) -> None:
    """同一业务记录被两份不同 checksum 的文档各自 staging 为 valid 时，
    publish 必须拒绝而不是让 IntegrityError 直接崩溃出来。"""
    config = load_pipeline_config("data_pipeline/configs/jiangsu.yaml")
    source = next(item for item in config.sources if item.id == "jseea-admission-score-2025")
    repository = PipelineRepository(session)
    repository.sync_sources(config)
    run = repository.start_run(source.id)

    document_a, _ = repository.register_document(
        run=run, source=source, artifact=_artifact(tmp_path, name="a", checksum="a" * 64), title="投档线-a"
    )
    document_b, _ = repository.register_document(
        run=run, source=source, artifact=_artifact(tmp_path, name="b", checksum="b" * 64), title="投档线-b"
    )
    validated = validate_records([_score()], config)
    staged_a = repository.stage_records(run=run, document=document_a, records=validated)
    staged_b = repository.stage_records(run=run, document=document_b, records=validated)

    with pytest.raises(PublicationError, match="natural key"):
        repository.publish(
            dataset_type="admission",
            province="江苏",
            year=2025,
            staging_records=[*staged_a, *staged_b],
        )
