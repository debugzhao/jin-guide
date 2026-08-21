"""Publish the already-collected, already-valid 2025 Jiangsu rank-segment
(一分一段/逐分段) staging records as an immutable dataset version.

Unlike admission scores, rank-segment records don't need cross-referencing
before publish — they ARE the reference table used to enrich admission
scores with min_rank (see loaders/enrichment.py). This script only exists
because that data was collected and validated (271 valid / 24 rejected by
the OCR quality gate) but was never actually published, so it never reached
`published_data_records` and therefore never reached the `rank_segments`
business table via business_sync.sync_rank_segments.

Usage:
    .venv/bin/python scripts/publish_jiangsu_rank_segments.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

YEAR = 2025


def run() -> dict:
    from sqlalchemy import select

    from app.database import SyncSessionLocal
    from app.models.data_pipeline import StagingRecord
    from data_pipeline.config import load_pipeline_config
    from data_pipeline.loaders import PipelineRepository

    config = load_pipeline_config(BACKEND_ROOT / "data_pipeline" / "configs" / "jiangsu.yaml")
    session = SyncSessionLocal()
    try:
        rows = [
            row
            for row in session.scalars(
                select(StagingRecord).where(StagingRecord.record_type == "RankSegmentRecord")
            ).all()
            if row.review_status == "valid"
            and row.payload_json.get("year") == YEAR
            and row.payload_json.get("province") == config.province
        ]
        if not rows:
            return {"published": None, "reason": "no valid RankSegmentRecord rows for this year"}

        repository = PipelineRepository(session)
        dataset = repository.publish(
            dataset_type="rank_segment",
            province=config.province,
            year=YEAR,
            staging_records=rows,
        )
        session.commit()
        return {
            "published": {
                "name": dataset.name,
                "version": dataset.version,
                "record_count": dataset.record_count,
            }
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
