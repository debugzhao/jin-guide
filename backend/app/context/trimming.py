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


def trim_history(
    messages: list[dict], max_messages: int, covered_through_seq: int | None = None
) -> list[dict]:
    """只保留最近 N 条原始消息（对应 §3.6 顺序表第 6 项）。

    `covered_through_seq` 是当前已经持久化的结构化摘要覆盖到的消息序号（与
    `messages` 的下标语义一致，1-indexed；不传或调用方没有摘要时退化成原来
    固定窗口裁剪）。摘要生成是异步 best-effort 任务（见 conversation_summary.py
    的 `maybe_generate_summary`），正常情况下每跨过一个窗口就会追上，但如果它
    还没来得及跑完（发消息发得比后台任务快）或者那一轮生成失败，固定窗口裁剪
    会把"已经滑出窗口但摘要还没盖住"的这部分消息直接丢弃且没有任何补偿——
    docs/context/ContextBuilder端到端验收用例.md E03 用例就实测到这个真实
    bug：第 10 轮摘要还没持久化完成就已经发出，窗口按固定 16 条把最早两条
    （预算、排除专业）连同摘要一起漏掉了。

    这里改成以"摘要实际覆盖到哪"为准：只裁掉摘要已确认覆盖的部分，未被覆盖
    的部分即使超过 max_messages 也保留，直到摘要追上来为止。上游
    `load_recent_messages_from_db`/`load_history_from_redis` 本身已经把
    history 封顶在 50 条左右（`conversation_store.MAX_MESSAGES_STORED`），
    所以最坏情况（摘要长期失败/从未生成）也只是退化成"发送全部原文"，不会
    真的无界增长。

    已知精度边界：`covered_through_seq` 是整个会话的全局序号，这里直接当成
    `messages` 列表下标使用——只要会话总消息数不超过上面那个 50 条上限，
    `messages[0]` 就正好是全局 seq=1，这个假设成立（E03/E11 两个验收用例都
    远小于 50 条）。一旦会话超过 50 条，`messages` 只是最近 50 条，
    `messages[0]` 对应的全局 seq 会大于 1 且不随会话增长而回传给这里，此时
    `covered_through_seq` 不再精确对应某个下标——不会越界或报错（`start`
    始终被夹在 `[0, default_start]` 之间），但窗口延伸的边界会失真（可能多留
    或少留几条），退化成一个尽力而为的启发式而不是精确对齐。要彻底修好需要
    把消息级 seq 一路带到 Redis 缓存的 JSON 里再传回这里，目前 Redis 缓存的
    消息只有 role/content/created_at，没有 seq——留作后续单独修复，这里先保证
    "不比修复前更差、且不崩溃"。
    """
    if covered_through_seq is None:
        return messages[-max_messages:]
    default_start = max(len(messages) - max_messages, 0)
    start = min(default_start, max(covered_through_seq, 0))
    return messages[start:]


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
