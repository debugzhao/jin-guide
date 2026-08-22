"""Publish the 2025 Shanghai policy (招生志愿填报与投档录取实施办法) staging
records as an immutable dataset version.

extract_policy_rule() always defaults ``batch`` to the constant "普通类本科批"
regardless of which batch the source document actually describes (it isn't
told which batch its input text belongs to). For most sources that default is
harmless because the document genuinely is about that one batch — but this
source is an entry HTML page plus 10 attachment PDFs, and several attachments
are 样表 (sample forms) for OTHER batches:

- "考生志愿表表4-本科普通批次（样表）" -> batch is genuinely 本科普通批次,
  parsed max_volunteers=24 (real: Shanghai本科普通批次 allows 24个院校专业组
  志愿, matches public knowledge) — this is the one this pipeline's scope
  (本科普通批次) actually needs, so it's kept and re-labeled to the batch
  string this project uses elsewhere ("本科普通批次", matching
  configs/shanghai.yaml / other publish scripts) instead of the generic
  default string.
- "考生志愿表表1-综合评价批次（样表）" (max_volunteers=4) and "考生志愿表
  表2-零志愿批次、本科提前批次、地方农村专项计划批次（样表）"
  (max_volunteers=3) are valid extractions but for DIFFERENT batches outside
  this pipeline's 本科普通批次 scope. Publishing them under the parser's
  default "普通类本科批" label would silently misattribute a 综合评价/提前批
  volunteer-count limit to 本科普通批次 rule lookups — worse than leaving them
  out. They are explicitly rejected here with a documented reason (not force-
  corrected into an invented batch string) rather than published.

Usage:
    .venv/bin/python scripts/publish_shanghai_policy.py
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
REVIEWER = "claude-code:shanghai-batch-mislabel-2025"
BATCH_LABEL = "本科普通批次"
OUT_OF_SCOPE_TITLES = {
    "2025年上海市普通高等学校招生考生志愿表表1-综合评价批次（样表）",
    "2025年上海市普通高等学校招生考生志愿表表2-零志愿批次、本科提前批次、地方农村专项计划批次（样表）",
}
IN_SCOPE_TITLE = "2025年上海市普通高等学校招生考生志愿表表4-本科普通批次（样表）"


def run() -> dict:
    from sqlalchemy import select

    from app.database import SyncSessionLocal
    from app.models.data_pipeline import StagingRecord
    from data_pipeline.config import load_pipeline_config
    from data_pipeline.loaders import PipelineRepository
    from data_pipeline.validators import validate_records
    from data_pipeline.records import PolicyRuleRecord

    config = load_pipeline_config(BACKEND_ROOT / "data_pipeline" / "configs" / "shanghai.yaml")
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

        rejected_out_of_scope = []
        in_scope_row = None
        now = datetime.now(UTC)
        for row in rows:
            title = row.payload_json.get("provenance", {}).get("source_title")
            if title in OUT_OF_SCOPE_TITLES and row.review_status == "valid":
                row.review_status = "rejected"
                row.reviewed_by = REVIEWER
                row.reviewed_at = now
                rejected_out_of_scope.append(title)
            elif title == IN_SCOPE_TITLE and row.review_status == "valid":
                in_scope_row = row

        if in_scope_row is None:
            session.rollback()
            return {
                "published": None,
                "reason": f"expected valid PolicyRuleRecord for {IN_SCOPE_TITLE!r} not found",
            }

        # 只改 batch 的展示字符串，不改 volunteer_mode/max_volunteers 等已解析出的
        # 真实字段——该文档本来就是本科普通批次的样表，只是parser默认label跟本
        # 项目其它地方用的"本科普通批次"写法不一致，这里对齐写法，不是编造数值
        corrected_payload = dict(in_scope_row.payload_json)
        corrected_payload["batch"] = BATCH_LABEL
        record = PolicyRuleRecord.model_validate(corrected_payload)
        (validated,) = validate_records([record], config)
        in_scope_row.payload_json = validated.payload
        in_scope_row.natural_key = validated.natural_key
        in_scope_row.issues_json = [issue.model_dump(mode="json") for issue in validated.issues]
        in_scope_row.review_status = validated.status
        if validated.status != "valid":
            session.rollback()
            return {
                "published": None,
                "reason": f"batch relabel made record {validated.status}: {validated.issues}",
            }

        session.flush()

        repository = PipelineRepository(session)
        dataset = repository.publish(
            dataset_type="policy",
            province=config.province,
            year=YEAR,
            staging_records=[in_scope_row],
        )
        session.commit()
        return {
            "rejected_out_of_scope": rejected_out_of_scope,
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
