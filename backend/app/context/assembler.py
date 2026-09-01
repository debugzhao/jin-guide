"""
按固定信任等级与顺序拼装最终 messages —— 对应 §3.6/§9.4/§10.2.5。

两个 Agent 现有的组装顺序已经基本符合目标模板（system → 状态数据/摘要/检索资料
→ 历史原文 → 当前请求），这里把顺序和信任包装规则固化成共享实现，不改变顺序
本身，只是不再由两个 Agent 各自重复实现一遍。
"""
from __future__ import annotations

from app.context.types import ContextItem
from app.prompts import wrap_untrusted_context


def wrap_item(item: ContextItem) -> str:
    """所有拼进 `dynamic_items` 的动态内容都要做不可信数据包装——system prompt
    本身不经过这里，由 `assemble_messages` 单独处理。即便是系统自己产出的业务
    数据（报告、结构化摘要），只要是运行期动态拼接的文本，就一律转义并打边界
    标签，防止其中混入的伪造指令被当成系统指令执行，这是当前两个 Agent 一直
    以来的实际行为。`item.trust_level` 只用于 manifest 标注来源的信任语义
    （对应 §9.4），不影响是否包装。
    """
    return item.prefix + wrap_untrusted_context(item.label, item.content)


def assemble_messages(
    *,
    system_prompt: str,
    dynamic_items: list[ContextItem],
    history: list[dict],
    user_message: str,
) -> list[dict]:
    """固定顺序：System → dynamic_items（按传入顺序，通常是状态数据/摘要/检索
    资料）→ 历史原文（保持原始 user/assistant 角色）→ 当前用户请求。

    只有 `included=True` 且内容非空的 `dynamic_items` 才会真正拼入——预算分配
    或裁剪阶段把某项标记为不含入时，这里不需要调用方再手动过滤一遍。
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for item in dynamic_items:
        if not item.included or not item.content:
            continue
        messages.append({"role": "user", "content": wrap_item(item)})
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages
