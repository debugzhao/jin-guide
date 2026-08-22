"""Publish the already-collected, already-valid 2025 Jiangsu policy
(招生工作意见) staging record as an immutable dataset version.

There are 2 PolicyRuleRecord staging rows for this source, both with the same
natural_key (province+year+batch+subject_type — policy rules don't carry a
per-document dimension):

- One parsed from the jseea.cn entry HTML page (an announcement blurb linking
  to the attachment) — every rule field came back empty/unknown, because the
  entry page genuinely doesn't contain the policy text, not because the parser
  is broken.
- One parsed from the linked PDF attachment — fully populated (volunteer_mode,
  max_volunteers, filing_rule, tie_break_rule).

Both being "valid" simultaneously would collide on natural_key at publish time
(``PipelineRepository.publish`` rejects duplicate natural keys), so the empty
HTML-derived row is explicitly marked ``rejected`` here (not force-approved —
its fields are genuinely absent from that document, approving it would violate
the "don't fabricate missing values" rule) before publishing the one real row.

Usage:
    .venv/bin/python scripts/publish_jiangsu_policy.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

YEAR = 2025
REVIEWER = "claude-code:duplicate-empty-entry-page"


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
                select(StagingRecord).where(StagingRecord.record_type == "PolicyRuleRecord")
            ).all()
            if row.payload_json.get("year") == YEAR
            and row.payload_json.get("province") == config.province
        ]

        rejected_empty_duplicate = []
        for row in rows:
            if row.review_status != "needs_review":
                continue
            payload = row.payload_json
            is_empty = all(
                payload.get(field) in (None, "unknown")
                for field in (
                    "volunteer_mode",
                    "max_volunteers",
                    "filing_rule",
                    "tie_break_rule",
                    "control_score",
                    "adjustment_allowed",
                    "adjustment_scope",
                )
            )
            if not is_empty:
                # Something unexpected is needs_review — do not silently reject it.
                raise RuntimeError(
                    f"staging record {row.id} is needs_review but not the known "
                    "empty-entry-page case; resolve manually before re-running"
                )
            row.review_status = "rejected"
            row.reviewed_by = REVIEWER
            row.reviewed_at = datetime.now(UTC)
            rejected_empty_duplicate.append(row.id)

        valid_rows = [row for row in rows if row.review_status == "valid"]
        if not valid_rows:
            session.rollback()
            return {"published": None, "reason": "no valid PolicyRuleRecord rows for this year"}

        repository = PipelineRepository(session)
        dataset = repository.publish(
            dataset_type="policy",
            province=config.province,
            year=YEAR,
            staging_records=valid_rows,
        )
        session.commit()
        return {
            "rejected_empty_duplicate_ids": rejected_empty_duplicate,
            "published": {
                "name": dataset.name,
                "version": dataset.version,
                "record_count": dataset.record_count,
            },
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
