"""Run the Shanghai official-data collection pipeline.

Examples:
    python scripts/run_shanghai_pipeline.py --source shmeea-policy-2025
    python scripts/run_shanghai_pipeline.py --all --persist
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from data_pipeline.config import load_pipeline_config
from data_pipeline.jobs import PipelineJob


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--source")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument(
        "--raw-root", type=Path, default=BACKEND_ROOT / "data" / "raw"
    )
    parser.add_argument(
        "--report-root", type=Path, default=BACKEND_ROOT / "data" / "reports"
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> list[dict]:
    config = load_pipeline_config(BACKEND_ROOT / "data_pipeline" / "configs" / "shanghai.yaml")
    if args.persist:
        from app.database import SyncSessionLocal

        session = SyncSessionLocal()
    else:
        session = None
    try:
        job = PipelineJob(
            config=config,
            raw_root=args.raw_root,
            report_root=args.report_root,
            session=session,
        )
        reports = await job.run_all() if args.all else [await job.run_source(args.source)]
        return [asdict(report) for report in reports]
    finally:
        if session:
            session.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(parse_args())), ensure_ascii=False, indent=2))
