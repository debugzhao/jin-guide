"""
合规自检 — 正则禁词检测 (M2 Layer 1).
M3 添加 LLM judge 语义过承诺检测 (Layer 2).
"""
from __future__ import annotations

import re

_FORBIDDEN: list[str] = [
    "保证录取",
    "必中",
    "精准录取",
    "包过",
    "保上",
    "百分百录取",
    "内部数据",
    "内部指标",
    "代替填报",
    "帮你填",
    "提供密码",
    "月薪保证",
    "薪资承诺",
]

_PATTERN = re.compile("|".join(re.escape(w) for w in _FORBIDDEN))


def check_compliance(text: str) -> list[str]:
    """
    Return list of forbidden phrases found in text.
    Empty list means compliant.
    """
    return list({m.group() for m in _PATTERN.finditer(text)})


def check_compliance_report(plan_json: dict) -> tuple[bool, list[str]]:
    """
    Flatten all text in plan_json and check for forbidden phrases.
    Returns (passed, issues).
    """
    full_text = _flatten_text(plan_json)
    issues = check_compliance(full_text)
    return len(issues) == 0, issues


def _flatten_text(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_flatten_text(item) for item in obj)
    if isinstance(obj, dict):
        return " ".join(_flatten_text(v) for v in obj.values())
    return ""
