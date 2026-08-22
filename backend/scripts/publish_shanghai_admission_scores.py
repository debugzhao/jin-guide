"""Collect the 2025 Shanghai admission-score sources (regular batch + Q-group/
中外合作 batch) and the score-distribution (rank-segment) source, enrich min_rank
via the score-distribution table, and publish an immutable admission dataset
version.

Shanghai's admission_score PDF explicitly withholds the投档线 for candidates
scoring 580 and above ("由市教育考试院会同考生所在中学逐一告知") — those rows are
skipped by parse_shmeea_admission_score_rows rather than fabricated, so this
dataset's coverage is intentionally partial for high-scoring groups (see
docs/10_shanghai_top10_data_collection_status.md).

Usage:
    .venv/bin/python scripts/publish_shanghai_admission_scores.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select

from data_pipeline.config import load_pipeline_config
from data_pipeline.jobs import PipelineJob
from data_pipeline.loaders import PipelineRepository, apply_admission_score_enrichment

YEAR = 2025
SOURCES = [
    "shmeea-admission-score-2025-general",
    "shmeea-admission-score-2025-cooperative",
    "shmeea-score-distribution-2025",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=BACKEND_ROOT / "data" / "raw")
    parser.add_argument("--report-root", type=Path, default=BACKEND_ROOT / "data" / "reports")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "collection staging is still persisted (PipelineJob commits per source); "
            "only the enrichment write-back and publish are rolled back / skipped"
        ),
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict:
    from app.database import SyncSessionLocal

    config = load_pipeline_config(BACKEND_ROOT / "data_pipeline" / "configs" / "shanghai.yaml")
    session = SyncSessionLocal()
    try:
        job = PipelineJob(
            config=config, raw_root=args.raw_root, report_root=args.report_root, session=session
        )
        collection_reports = [(await job.run_source(source_id)).__dict__ for source_id in SOURCES]

        enrichment_summary = apply_admission_score_enrichment(session, config=config, year=YEAR)

        from app.models.data_pipeline import StagingRecord

        score_rows = [
            row
            for row in session.scalars(
                select(StagingRecord).where(StagingRecord.record_type == "AdmissionScoreRecord")
            ).all()
            if row.payload_json.get("year") == YEAR
            and row.payload_json.get("province") == config.province
        ]

        result = {"collection": collection_reports, "enrichment": enrichment_summary}

        if args.dry_run:
            session.rollback()
            result["published"] = None
            return result

        repository = PipelineRepository(session)
        valid_rows = [row for row in score_rows if row.review_status == "valid"]
        if not valid_rows:
            result["published"] = None
            result["reason"] = "no valid AdmissionScoreRecord rows for this year"
            return result
        dataset = repository.publish(
            dataset_type="admission",
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
        result["needs_review_count"] = sum(
            1 for row in score_rows if row.review_status == "needs_review"
        )
        return result
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(parse_args())), ensure_ascii=False, indent=2, default=str))
