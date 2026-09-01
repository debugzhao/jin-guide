"""共享的"不可信数据"包装工具。

任何拼进 Prompt 的动态内容（用户输入、检索结果、历史摘要等）只要不是本模块
固定撰写的指令文本，都必须经这里转义并打上 trust="untrusted-data" 标签再拼接，
否则其中可能出现的伪造标签或指令文本会和真正的系统指令混在一起、被模型当成
指令执行——这正是 Prompt 注入的入口。此前 conversation_agent.py / intake_agent.py
各自维护一份同名私有函数，容易在新增调用点时被漏用或写出不一致的标签，这里收敛
成唯一实现。
"""
from __future__ import annotations

from html import escape


def wrap_untrusted_context(tag: str, content: str) -> str:
    return f'<{tag} trust="untrusted-data">\n{escape(content, quote=False)}\n</{tag}>'
