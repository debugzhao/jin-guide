"""
共享的历史裁剪、摘要渲染与结构化裁剪工具 —— 见 §10.2.1/§10.2.6。

原来 conversation_agent.py 和 intake_agent.py 各自维护一份几乎相同的
`_trim_history`/`_build_summary_block`，这里收敛成唯一实现；两个 Agent 模块的
同名函数改为对这里的薄封装，保留原有函数签名以兼容既有测试对它们的直接调用。
"""
from __future__ import annotations

import copy
import json

DEFAULT_SUMMARY_LABELS: dict[str, str] = {
    "confirmed_facts": "已确认信息",
    "preferences": "已表达偏好",
    "rejected_options": "已排除选项",
    "previous_decisions": "此前已做出的结论",
    "open_questions": "待跟进问题",
}


def trim_history(messages: list[dict], max_messages: int) -> list[dict]:
    """只保留最近 N 条原始消息（对应 §3.6 顺序表第 6 项）。"""
    return messages[-max_messages:]


def render_summary_block(summary: dict | None, labels: dict[str, str] | None = None) -> str:
    """把结构化增量摘要渲染成精简文本块（对应 §9.5 摘要定位）。"""
    if not summary:
        return ""
    labels = labels or DEFAULT_SUMMARY_LABELS
    parts = []
    for key, label in labels.items():
        values = summary.get(key) or []
        if values:
            parts.append(f"{label}：" + "；".join(str(v) for v in values))
    return "\n".join(parts)


def _drop_longest_list_item(obj) -> bool:
    """在 obj 的直接子层找出最长的列表字段并弹出其最后一个元素；obj 本身是
    列表则直接弹出最后一个元素。返回是否成功丢弃了一个元素——按对象边界裁剪
    （对应 §4.8/§8.7），不在字符串中间硬切。"""
    if isinstance(obj, list):
        if obj:
            obj.pop()
            return True
        return False
    if isinstance(obj, dict):
        list_fields = [(k, v) for k, v in obj.items() if isinstance(v, list) and v]
        if not list_fields:
            return False
        _, longest = max(list_fields, key=lambda kv: len(json.dumps(kv[1], ensure_ascii=False)))
        longest.pop()
        return True
    return False


def truncate_structured(value: dict | list, max_chars: int) -> tuple[str, bool]:
    """把 JSON 对象/列表裁剪到 max_chars 以内，优先整体丢弃列表末尾元素，只有
    列表已经丢无可丢时才退化为字符硬切兜底（此时说明单个元素本身就超出预算，
    结构化裁剪已经无能为力）。

    Returns (最终文本, 是否发生过裁剪)。
    """
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= max_chars:
        return text, False

    obj = copy.deepcopy(value)
    while len(text) > max_chars:
        if not _drop_longest_list_item(obj):
            return text[:max_chars] + "...(已截断)", True
        text = json.dumps(obj, ensure_ascii=False)
    return text, True
