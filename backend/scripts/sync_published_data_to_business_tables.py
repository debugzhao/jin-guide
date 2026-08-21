"""把 published_data_records 同步进业务表 admission_scores/rank_segments/admission_plans。

发布区（published_data_records）和业务查询表刻意分离，数据发布后不会自动生效，
必须显式跑这一步——见 data_pipeline/loaders/business_sync.py 顶部说明。

Usage:
    .venv/bin/python scripts/sync_published_data_to_business_tables.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def run() -> dict:
    from app.database import SyncSessionLocal
    from data_pipeline.loaders import sync_all

    session = SyncSessionLocal()
    try:
        results = sync_all(session)
        session.commit()
        return {
            result.record_type: {
                "seen": result.seen,
                "created": result.created,
                "updated": result.updated,
                "skipped_missing_university": result.skipped_missing_university,
            }
            for result in results
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
