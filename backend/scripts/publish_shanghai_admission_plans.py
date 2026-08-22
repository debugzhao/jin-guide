"""Stage and publish the 2026 Shanghai admission-plan (招生计划) records
collected manually via Playwright from each target university's own
admissions website (JS-rendered query systems) or, for 上海交通大学, from an
OCR'd newspaper-style plan image — see
backend/data_pipeline/docs/10_shanghai_top10_data_collection_status.md for
per-school collection notes and known gaps (复旦大学 not published by the
school for 2025/2026; 东华大学 has no web-accessible source, only its WeChat
mini-program).

Each school's extracted rows live in
data/raw/上海/2026/admission-plan-manual/<code>_<school>.json, committed as
raw evidence matching RawArtifactStore's role for the http-collected sources.
This script turns those into AdmissionPlanRecord objects (subject_type=
"unified" — Shanghai's "3+3" doesn't split by 物理/历史), runs them through
the same validate_records()/stage_records()/publish() pipeline as every other
data type, then syncs the published records into admission_plans via
business_sync.

Usage:
    .venv/bin/python scripts/publish_shanghai_admission_plans.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

YEAR = 2026
DEFAULT_BATCH = "本科普通批次"
RAW_DIR = BACKEND_ROOT / "data" / "raw" / "上海" / "2026" / "admission-plan-manual"


def run() -> dict:
    from data_pipeline.config import load_pipeline_config
    from data_pipeline.loaders import PipelineRepository, sync_admission_plans
    from data_pipeline.raw_store import StoredArtifact
    from data_pipeline.records import AdmissionPlanRecord, Provenance
    from data_pipeline.validators import validate_records

    from app.database import SyncSessionLocal

    config = load_pipeline_config(BACKEND_ROOT / "data_pipeline" / "configs" / "shanghai.yaml")
    sources_by_code = {
        s.target_university_code: s for s in config.sources if s.collection_method == "manual"
    }

    session = SyncSessionLocal()
    try:
        repository = PipelineRepository(session)
        repository.sync_sources(config)

        all_staged = []
        per_school_summary = []
        for json_path in sorted(RAW_DIR.glob("*.json")):
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            code = payload["university_code"]
            source = sources_by_code[code]

            run_row = repository.start_run(source.id)
            content = json_path.read_bytes()
            artifact = StoredArtifact(
                source_id=source.id,
                source_url=payload.get("source_image_local")
                or payload.get("source_image")
                or payload["source_url"],
                checksum=hashlib.sha256(content).hexdigest(),
                content_path=json_path,
                metadata_path=json_path,
                collected_at=payload["collected_at"],
                changed=True,
                size_bytes=len(content),
            )
            document, _ = repository.register_document(
                run=run_row,
                source=source,
                artifact=artifact,
                title=f"{payload['university_name']}2026年招生计划",
                content_type="application/json",
            )

            provenance_kwargs = dict(
                source_url=artifact.source_url,
                source_document_id=document.id,
                source_title=f"{payload['university_name']}2026年招生计划",
                year=YEAR,
                authority_level="official",
                collected_at=payload["collected_at"],
                parser_version=payload["parser_version"],
            )
            records = []
            for row in payload["rows"]:
                restrictions_parts = []
                if row.get("college"):
                    restrictions_parts.append(f"培养学院：{row['college']}")
                if row.get("restrictions"):
                    restrictions_parts.append(row["restrictions"])
                records.append(
                    AdmissionPlanRecord(
                        province=config.province,
                        year=YEAR,
                        batch=row.get("batch", DEFAULT_BATCH),
                        subject_type="unified",
                        university_code=code,
                        university_name=payload["university_name"],
                        major_group_code=row.get("major_group_code"),
                        major_name=row["major_name"],
                        quota=row["quota"],
                        tuition=row.get("tuition"),
                        selection_requirement=row.get("selection_requirement"),
                        admission_type=row.get("admission_type", "普通"),
                        restrictions="；".join(restrictions_parts) or None,
                        provenance=Provenance(**provenance_kwargs),
                    )
                )
            validated = validate_records(records, config)
            staged = repository.stage_records(run=run_row, document=document, records=validated)
            repository.finish_run(run_row)
            all_staged.extend(staged)
            per_school_summary.append(
                {
                    "university_code": code,
                    "university_name": payload["university_name"],
                    "parsed": len(staged),
                    "valid": sum(1 for r in staged if r.review_status == "valid"),
                    "needs_review": sum(1 for r in staged if r.review_status == "needs_review"),
                    "rejected": sum(1 for r in staged if r.review_status == "rejected"),
                }
            )
        session.commit()

        valid_rows = [r for r in all_staged if r.review_status == "valid"]
        blocked = [r for r in all_staged if r.review_status != "valid"]
        result = {"collection": per_school_summary, "blocked_count": len(blocked)}
        if blocked:
            result["blocked_natural_keys"] = [r.natural_key for r in blocked]
        if not valid_rows:
            result["published"] = None
            return result

        dataset = repository.publish(
            dataset_type="plan",
            province=config.province,
            year=YEAR,
            staging_records=valid_rows,
        )
        session.commit()
        result["published"] = {
            "name": dataset.name,
            "version": dataset.version,
            "record_count": dataset.record_count,
        }

        sync_result = sync_admission_plans(session)
        session.commit()
        result["synced"] = {
            "seen": sync_result.seen,
            "created": sync_result.created,
            "updated": sync_result.updated,
            "skipped_missing_university": sync_result.skipped_missing_university,
        }
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
