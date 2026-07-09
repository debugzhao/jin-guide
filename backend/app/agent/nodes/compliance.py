"""
合规自检 — 正则禁词检测 (M2 Layer 1).
M3 添加 LLM judge 语义过承诺检测 (Layer 2, 见 reflection_agent.py)。

_FORBIDDEN_REPLACEMENTS 是全项目唯一的禁词配置源：Reflection Agent（report 主链路）
和 ConversationAgent（报告问答）的正则层都从这里读取检测词表和安全替换文案，
避免两处各维护一份词表导致漂移（例如某个词只在一处能被替换，另一处只报警不替换）。
"""
from __future__ import annotations

import re

_FORBIDDEN_REPLACEMENTS: dict[str, str] = {
    "保证录取": "有录取可能",
    "必中": "有较大概率录取",
    "精准录取": "预计录取",
    "包过": "通过概率较高",
    "保上": "安全边际较充足",
    "百分百录取": "预计录取概率较高",
    "内部数据": "公开数据",
    "内部指标": "公开指标",
    "代替填报": "辅助填报",
    "帮你填": "辅助你填写",
    "提供密码": "（已移除敏感内容）",
    "月薪保证": "薪资参考区间",
    "薪资承诺": "薪资参考区间",
    "稳拿": "有较大把握",
    "必然上岸": "预计可以录取",
}

_FORBIDDEN: list[str] = list(_FORBIDDEN_REPLACEMENTS.keys())

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


def sanitize_text(text: str) -> str:
    """将文本中出现的禁词替换为安全表述（ConversationAgent 实时问答场景使用）。"""
    for word, replacement in _FORBIDDEN_REPLACEMENTS.items():
        text = text.replace(word, replacement)
    return text


def _flatten_text(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_flatten_text(item) for item in obj)
    if isinstance(obj, dict):
        return " ".join(_flatten_text(v) for v in obj.values())
    return ""
