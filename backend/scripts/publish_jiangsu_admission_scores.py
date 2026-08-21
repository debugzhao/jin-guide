"""Persist 2025 Jiangsu admission-score + rank-segment sources, enrich min_rank,
and publish an immutable admission dataset version.

The 4 manual overrides below are NOT estimated: each value was read directly off
the official rank-segment source image at the row for that score (see
docs/08_jiangsu_data_pipeline_handoff.md §"needs_review" diagnosis). The parser's
OCR either misread the cumulative-rank column (644/595/636 -> quality gate
rejected the row as non-monotonic) or skipped the row outright (643).

Usage:
    .venv/bin/python scripts/publish_jiangsu_admission_scores.py
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
MANUAL_RANK_OVERRIDES = {
    ("physics", 644): 6362,
    ("physics", 595): 39620,
    ("history", 643): 497,
    ("history", 636): 828,
}
REVIEWER = "claude-code:image-verified-jseea-rank-segment-2025"


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

    config = load_pipeline_config(BACKEND_ROOT / "data_pipeline" / "configs" / "jiangsu.yaml")
    session = SyncSessionLocal()
    try:
        job = PipelineJob(
            config=config, raw_root=args.raw_root, report_root=args.report_root, session=session
        )
        collection_reports = [
            (await job.run_source("jseea-admission-score-2025")).__dict__,
            (await job.run_source("jseea-rank-segment-2025")).__dict__,
        ]

        enrichment_summary = apply_admission_score_enrichment(
            session,
            config=config,
            year=YEAR,
            manual_rank_overrides=MANUAL_RANK_OVERRIDES,
            reviewer=REVIEWER,
        )

        from app.models.data_pipeline import StagingRecord

        score_rows = [
            row
            for row in session.scalars(
                select(StagingRecord).where(StagingRecord.record_type == "AdmissionScoreRecord")
            ).all()
            if row.payload_json.get("year") == YEAR
        ]

        result = {
            "collection": collection_reports,
            "enrichment": enrichment_summary,
        }

        if args.dry_run:
            session.rollback()
            result["published"] = None
            return result

        repository = PipelineRepository(session)
        valid_rows = [row for row in score_rows if row.review_status == "valid"]
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
        return result
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(parse_args())), ensure_ascii=False, indent=2, default=str))
