"""
游标分页公共工具 (CLAUDE.md「分页规范」、docs/backend-prd-v2.md §5.4)。
所有列表接口用不透明游标而非 offset，避免深分页时的性能问题和数据漂移。
"""
from __future__ import annotations

import base64
import json
from datetime import datetime


def encode_cursor(created_at: datetime, id_: str) -> str:
    payload = json.dumps({"created_at": created_at.isoformat(), "id": id_})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Raises ValueError on a malformed/tampered cursor."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["created_at"]), payload["id"]
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
