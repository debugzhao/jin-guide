"""Attach exact ranks to staged admission-score records using rank segments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from data_pipeline.config import load_pipeline_config
from data_pipeline.records import AdmissionScoreRecord, RankSegmentRecord, ValidatedRecord
from data_pipeline.validators import attach_min_ranks, validate_records


def _read_validated(path: Path) -> list[ValidatedRecord]:
    return [
        ValidatedRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run(scores_path: Path, ranks_path: Path, output_path: Path) -> dict:
    config = load_pipeline_config(BACKEND_ROOT / "data_pipeline" / "configs" / "jiangsu.yaml")
    score_rows = _read_validated(scores_path)
    rank_rows = _read_validated(ranks_path)
    scores = [
        AdmissionScoreRecord.model_validate(row.payload)
        for row in score_rows
        if row.record_type == "AdmissionScoreRecord" and row.status != "rejected"
    ]
    ranks = [
        RankSegmentRecord.model_validate(row.payload)
        for row in rank_rows
        if row.record_type == "RankSegmentRecord" and row.status == "valid"
    ]
    enriched = validate_records(attach_min_ranks(scores, ranks), config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(record.model_dump_json() + "\n" for record in enriched),
        encoding="utf-8",
    )
    summary = {
        "score_records": len(scores),
        "rank_records": len(ranks),
        "valid": sum(record.status == "valid" for record in enriched),
        "needs_review": sum(record.status == "needs_review" for record in enriched),
        "rejected": sum(record.status == "rejected" for record in enriched),
        "output": str(output_path),
    }
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--ranks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.scores, args.ranks, args.output), ensure_ascii=False, indent=2))
