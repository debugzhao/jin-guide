"""Attach exact ranks to staged 浙江 AdmissionScoreRecord rows that lack them.

浙江省考试院原始投档线表（zjzs_admission_score_v1）自带位次，采集时就已经
填好 min_rank，不需要这一步；但学校自采的"历年分数"补充数据不一定有位次列
——浙江工商大学"历年分数"JSON接口（zjgsu_admission_score_json_v1）只有
最低/最高/平均分，没有位次，55条记录全部卡在 needs_review（见状态看板#9）。

跟 scripts/publish_jiangsu_admission_scores.py 里内嵌调用 enrichment 不同，
浙江这批数据是分开采集/发布的（先 collect 到 staging，再单独 publish），所以
enrichment 需要能单独对已经落库的 staging 记录跑一遍，直接复用
`data_pipeline.loaders.apply_admission_score_enrichment`（按 subject_type+
min_score 去匹配同 province+year 的 RankSegmentRecord，浙江"3+3不分文理"
subject_type 恒为 unified，只要分数命中 rank_segment 表就能精确匹配到位次，
不需要像江苏那样区分物理/历史两张表）。

Usage:
    docker compose exec backend python -m scripts.enrich_zhejiang_scores --year 2025
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=BACKEND_ROOT / "data_pipeline" / "configs" / "zhejiang.yaml",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    from app.database import SyncSessionLocal
    from data_pipeline.config import load_pipeline_config
    from data_pipeline.loaders import apply_admission_score_enrichment

    config = load_pipeline_config(args.config)
    session = SyncSessionLocal()
    try:
        summary = apply_admission_score_enrichment(session, config=config, year=args.year)
        session.commit()
        return summary
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, default=str))
