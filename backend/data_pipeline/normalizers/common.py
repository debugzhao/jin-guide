from __future__ import annotations

import re

from data_pipeline.records import SubjectType


def normalize_subject_type(value: str) -> SubjectType:
    normalized = re.sub(r"\s+", "", value).lower()
    if normalized in {"physics", "物理", "物理类", "物理等科目类"}:
        return "physics"
    if normalized in {"history", "历史", "历史类", "历史等科目类"}:
        return "history"
    raise ValueError(f"unsupported subject type: {value!r}")


def normalize_batch(value: str) -> str:
    normalized = re.sub(r"\s+", "", value)
    aliases = {
        "普通本科批": "本科批",
        "普通类本科批": "本科批",
        "本科普通批": "本科批",
        "本科提前批次": "本科提前批",
        "专科批次": "专科批",
    }
    return aliases.get(normalized, normalized)
