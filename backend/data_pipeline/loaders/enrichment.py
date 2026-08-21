"""Reconcile score/rank enrichment results back into DB-backed staging records.

The collection pipeline stages ``AdmissionScoreRecord`` and ``RankSegmentRecord``
rows independently (one document -> one ``stage_records`` call). Cross-referencing
a score's ``min_score`` against the rank-segment table to fill in ``min_rank``
happens after both are staged, so it needs a separate pass over already-persisted
``StagingRecord`` rows rather than living inside ``PipelineJob``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_pipeline import StagingRecord
from data_pipeline.config import PipelineConfig
from data_pipeline.records import AdmissionScoreRecord, RankSegmentRecord
from data_pipeline.validators import attach_min_ranks, validate_records

# Keyed by (subject_type, min_score) -> cumulative_rank read directly off the
# official rank-segment source image (not inferred). Used only when the parser
# either misread or completely missed that score's row in the rank-segment table.
ManualRankOverride = dict[tuple[str, int], int]


def apply_admission_score_enrichment(
    session: Session,
    *,
    config: PipelineConfig,
    year: int,
    manual_rank_overrides: ManualRankOverride | None = None,
    reviewer: str | None = None,
) -> dict:
    manual_rank_overrides = manual_rank_overrides or {}
    province = config.province

    rank_rows = session.scalars(
        select(StagingRecord).where(StagingRecord.record_type == "RankSegmentRecord")
    ).all()
    ranks = [
        RankSegmentRecord.model_validate(row.payload_json)
        for row in rank_rows
        if row.review_status == "valid"
        and row.payload_json.get("province") == province
        and row.payload_json.get("year") == year
    ]

    score_rows = [
        row
        for row in session.scalars(
            select(StagingRecord).where(StagingRecord.record_type == "AdmissionScoreRecord")
        ).all()
        if row.payload_json.get("province") == province and row.payload_json.get("year") == year
    ]
    scores = [AdmissionScoreRecord.model_validate(row.payload_json) for row in score_rows]

    enriched = attach_min_ranks(scores, ranks)
    manually_corrected_keys: set[str] = set()
    for record in enriched:
        if record.min_rank is not None:
            continue
        override = manual_rank_overrides.get((record.subject_type, record.min_score))
        if override is not None:
            record.min_rank = override
            manually_corrected_keys.add(
                f"{record.subject_type}:{record.min_score}:{record.university_code}:{record.major_group_code}"
            )

    revalidated = validate_records(enriched, config)
    by_natural_key = {row.natural_key: row for row in score_rows}
    now = datetime.now(UTC)
    manually_verified = 0
    for validated in revalidated:
        row = by_natural_key[validated.natural_key]
        row.payload_json = validated.payload
        row.issues_json = [issue.model_dump(mode="json") for issue in validated.issues]
        row.review_status = validated.status
        key = (
            f"{validated.payload.get('subject_type')}:{validated.payload.get('min_score')}:"
            f"{validated.payload.get('university_code')}:{validated.payload.get('major_group_code')}"
        )
        if key in manually_corrected_keys and validated.status == "valid":
            row.reviewed_by = reviewer or "manual:image-verified"
            row.reviewed_at = now
            manually_verified += 1

    session.flush()
    return {
        "province": province,
        "year": year,
        "score_records": len(score_rows),
        "rank_records": len(ranks),
        "manually_verified": manually_verified,
        "valid": sum(1 for item in revalidated if item.status == "valid"),
        "needs_review": sum(1 for item in revalidated if item.status == "needs_review"),
        "rejected": sum(1 for item in revalidated if item.status == "rejected"),
    }
