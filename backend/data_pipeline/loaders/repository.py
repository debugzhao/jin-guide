from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_pipeline import (
    CollectionRun,
    DataSource,
    DatasetVersion,
    PublishedDataRecord,
    SourceDocument,
    StagingRecord,
)
from app.models.document import Chunk, Document
from data_pipeline.config import PipelineConfig, SourceConfig
from data_pipeline.raw_store import StoredArtifact
from data_pipeline.records import ValidatedRecord


class PublicationError(RuntimeError):
    pass


class PipelineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def sync_sources(self, config: PipelineConfig) -> None:
        now = datetime.now(UTC)
        for source in config.sources:
            model = self.session.get(DataSource, source.id)
            values = self._source_values(source)
            if model is None:
                self.session.add(DataSource(id=source.id, created_at=now, updated_at=now, **values))
            else:
                for key, value in values.items():
                    setattr(model, key, value)
                model.updated_at = now
        self.session.flush()

    def start_run(self, source_id: str) -> CollectionRun:
        run = CollectionRun(source_id=source_id, status="running")
        self.session.add(run)
        self.session.flush()
        return run

    def register_document(
        self,
        *,
        run: CollectionRun,
        source: SourceConfig,
        artifact: StoredArtifact,
        title: str,
        content_type: str | None = None,
    ) -> tuple[SourceDocument, bool]:
        existing = self.session.scalar(
            select(SourceDocument).where(
                SourceDocument.source_id == source.id,
                SourceDocument.checksum == artifact.checksum,
            )
        )
        if existing is not None:
            return existing, False
        document = SourceDocument(
            source_id=source.id,
            collection_run_id=run.id,
            source_url=artifact.source_url,
            title=title,
            checksum=artifact.checksum,
            storage_path=str(artifact.content_path),
            content_type=content_type,
            size_bytes=artifact.size_bytes,
            status="raw",
            collected_at=datetime.fromisoformat(artifact.collected_at),
        )
        self.session.add(document)
        run.artifact_count += 1
        self.session.flush()
        return document, True

    def stage_records(
        self,
        *,
        run: CollectionRun,
        document: SourceDocument,
        records: Iterable[ValidatedRecord],
    ) -> list[StagingRecord]:
        staged: list[StagingRecord] = []
        for record in records:
            existing = self.session.scalar(
                select(StagingRecord).where(
                    StagingRecord.source_document_id == document.id,
                    StagingRecord.natural_key == record.natural_key,
                )
            )
            if existing is not None:
                staged.append(existing)
                continue
            model = StagingRecord(
                source_document_id=document.id,
                collection_run_id=run.id,
                record_type=record.record_type,
                natural_key=record.natural_key,
                review_status=record.status,
                payload_json=record.payload,
                issues_json=[issue.model_dump(mode="json") for issue in record.issues],
            )
            self.session.add(model)
            staged.append(model)
            run.parsed_count += 1
            if record.status == "valid":
                run.valid_count += 1
            elif record.status == "needs_review":
                run.review_count += 1
            else:
                run.rejected_count += 1
        document.status = "parsed"
        self.session.flush()
        self._sync_rag_chunks(document, staged)
        return staged

    def finish_run(self, run: CollectionRun, *, error: Exception | None = None) -> None:
        run.finished_at = datetime.now(UTC)
        run.status = "failed" if error else "succeeded"
        run.error_message = str(error)[:4000] if error else None
        if error is None:
            source = self.session.get(DataSource, run.source_id)
            if source is not None:
                source.last_success_at = run.finished_at
        self.session.flush()

    def publish(
        self,
        *,
        dataset_type: str,
        province: str,
        year: int,
        staging_records: Iterable[StagingRecord],
    ) -> DatasetVersion:
        records = list(staging_records)
        if not records:
            raise PublicationError("cannot publish an empty dataset")
        blocked = [record for record in records if record.review_status != "valid"]
        if blocked:
            raise PublicationError(
                f"cannot publish: {len(blocked)} record(s) still require review or are rejected"
            )
        record_types = {record.record_type for record in records}
        if len(record_types) != 1:
            raise PublicationError("one dataset version may contain only one record type")

        # 同一来源被重新采集后（哪怕只是页面渲染字节差异导致 checksum 变化），
        # 可能产生 source_document_id 不同但业务自然键相同的两条 "valid" staging
        # 记录——按文档级别去重的校验（validate_records）和 uq_staging_document_
        # natural_key 唯一约束都不会拦住它们。这里只对 AdmissionScoreRecord 之外
        # 的记录类型兜底（AdmissionScoreRecord 已由 enrichment 的跨文档重新校验
        # 覆盖），避免它们在插入 published_data_records 时撞上
        # uq_published_dataset_natural_key 唯一约束、以未处理的 IntegrityError 崩溃。
        duplicate_keys = {
            key for key, count in Counter(record.natural_key for record in records).items()
            if count > 1
        }
        if duplicate_keys:
            raise PublicationError(
                f"cannot publish: {len(duplicate_keys)} natural key(s) appear in more than "
                "one valid staging record; resolve the duplicate source documents before publishing"
            )

        previous = self.session.scalar(
            select(func.max(DatasetVersion.version)).where(
                DatasetVersion.dataset_type == dataset_type,
                DatasetVersion.province == province,
                DatasetVersion.year == year,
            )
        )
        version_number = (previous or 0) + 1
        scope = "top10" if dataset_type in {"admission", "plan"} else "policy"
        name = f"jiangsu_{scope}_{year}_{dataset_type}_v{version_number}"
        dataset = DatasetVersion(
            name=name,
            dataset_type=dataset_type,
            province=province,
            year=year,
            version=version_number,
            status="published",
            record_count=len(records),
            manifest_json={
                "staging_record_ids": [record.id for record in records],
                "source_document_ids": sorted({record.source_document_id for record in records}),
            },
            published_at=datetime.now(UTC),
        )
        self.session.add(dataset)
        self.session.flush()

        for record in records:
            payload = record.payload_json
            provenance = payload.get("provenance") or {}
            self.session.add(
                PublishedDataRecord(
                    dataset_version_id=dataset.id,
                    record_type=record.record_type,
                    natural_key=record.natural_key,
                    province=payload.get("province", province),
                    year=payload.get("year", year),
                    subject_type=payload.get("subject_type"),
                    batch=payload.get("batch"),
                    university_code=payload.get("university_code"),
                    major_group_code=payload.get("major_group_code"),
                    major_code=payload.get("major_code"),
                    payload_json=payload,
                    provenance_json=provenance,
                )
            )
        self.session.flush()
        return dataset

    @staticmethod
    def _source_values(source: SourceConfig) -> dict:
        return {
            "name": source.name,
            "entry_url": str(source.entry_url),
            "data_type": source.data_type,
            "year": source.year,
            "target_university_code": source.target_university_code,
            "collection_method": source.collection_method,
            "parser": source.parser,
            "update_frequency": source.update_frequency,
            "authority_level": source.authority_level,
            "enabled": source.enabled,
        }

    def _sync_rag_chunks(
        self, source_document: SourceDocument, staged: list[StagingRecord]
    ) -> None:
        chunks = [
            record
            for record in staged
            if record.record_type == "DocumentChunkRecord" and record.review_status == "valid"
        ]
        if not chunks:
            return
        document = self.session.scalar(
            select(Document).where(Document.source_document_id == source_document.id)
        )
        if document is None:
            first = chunks[0].payload_json
            document = Document(
                type=first["document_type"],
                title=source_document.title,
                source_url=source_document.source_url,
                year=first["year"],
                authority_level=first["provenance"]["authority_level"],
                checksum=source_document.checksum,
                source_document_id=source_document.id,
                raw_storage_path=source_document.storage_path,
                status="parsed",
            )
            self.session.add(document)
            self.session.flush()
        existing_indexes = {
            (chunk.metadata_json or {}).get("chunk_index")
            for chunk in self.session.scalars(
                select(Chunk).where(Chunk.document_id == document.id)
            )
        }
        for staged_chunk in chunks:
            payload = staged_chunk.payload_json
            index = payload["chunk_index"]
            if index in existing_indexes:
                continue
            self.session.add(
                Chunk(
                    document_id=document.id,
                    content=payload["content"],
                    metadata_json={
                        "province": payload["province"],
                        "year": payload["year"],
                        "university_code": payload.get("university_code"),
                        "doc_type": payload["document_type"],
                        "section_title": payload.get("section_title"),
                        "chunk_index": index,
                        "source_url": payload["provenance"]["source_url"],
                        "page_number": payload["provenance"].get("page_number"),
                    },
                )
            )
        self.session.flush()
