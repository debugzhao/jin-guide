"""Publish already-collected, already-valid 浙江 staging records as an
immutable dataset version.

跟江苏 rank_segment/policy 一样，浙江这几类记录本身就不需要额外的
enrichment 步骤才能发布：
- RankSegmentRecord/PolicyRuleRecord：跟江苏一样，采集时就是最终形态；
- AdmissionScoreRecord：浙江投档线原始表本身就带位次列（学校代号/学校名称/
  专业代号/专业名称/计划数/分数线/位次），parse_zhejiang_admission_score_rows
  采集时已经直接填好 min_rank，不像江苏投档线需要另外关联逐分段表才能补全位次
  （见 loaders/enrichment.py），所以这里没有对应的 enrichment 调用；
- AdmissionPlanRecord：10校招生计划里目前只有3校（宁波大学/浙江理工大学/
  杭州师范大学）通过 http 直采验证过，一并发布，其余7校缺口见状态看板。

一个 dataset_version 只能装一种 record_type（PipelineRepository.publish 的
硬性要求），所以按 --record-type + --year 发布，同一年份下不同批次
（如投档线的"第一段"/"第二段"、不同学校）的 valid 记录会合并进同一个
dataset_version（natural_key 已经把 batch/university_code 编码进去，不会
互相覆盖）。

Usage:
    docker compose exec backend python -m scripts.publish_zhejiang_data \\
        --record-type RankSegmentRecord --year 2026
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_DATASET_TYPES = {
    "RankSegmentRecord": "rank_segment",
    "PolicyRuleRecord": "policy",
    "AdmissionScoreRecord": "admission",
    "AdmissionPlanRecord": "plan",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-type", required=True, choices=sorted(_DATASET_TYPES))
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=BACKEND_ROOT / "data_pipeline" / "configs" / "zhejiang.yaml",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    from sqlalchemy import select

    from app.database import SyncSessionLocal
    from app.models.data_pipeline import StagingRecord
    from data_pipeline.config import load_pipeline_config
    from data_pipeline.loaders import PipelineRepository

    config = load_pipeline_config(args.config)
    session = SyncSessionLocal()
    try:
        rows = [
            row
            for row in session.scalars(
                select(StagingRecord).where(StagingRecord.record_type == args.record_type)
            ).all()
            if row.review_status == "valid"
            and row.payload_json.get("year") == args.year
            and row.payload_json.get("province") == config.province
        ]
        if not rows:
            return {
                "published": None,
                "reason": f"no valid {args.record_type} rows for {args.year}",
            }

        repository = PipelineRepository(session)
        dataset = repository.publish(
            dataset_type=_DATASET_TYPES[args.record_type],
            province=config.province,
            year=args.year,
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
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, default=str))
