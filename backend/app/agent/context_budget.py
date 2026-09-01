"""
Token 计数原语 —— 见 docs/context/上下文模块评审.md §10.2.7。

`count_tokens` 用 tiktoken 的 cl100k_base 编码近似估算——kimi-k2.6 没有公开的
官方 tokenizer，这里只需要同一次请求内不同来源之间的相对比较，不需要字节级
精确；真实精确值可以从 LangSmith 里查每次调用的 usage 字段。

跟 LangSmith 的分工：LangSmith（已通过 litellm_config.yaml 的 success_callback
接好）能看到每次调用的真实总 token 数和成本趋势，但看不到"这些 token 里哪部分
来自证据、哪部分来自历史"——这个语义归因只存在于组装 Prompt 的代码里，一旦拼成
扁平的 messages 数组发出去就丢失了，所以这部分必须在这里算，不能指望 LangSmith
替代（详见 docs/疑问杂项.md）。

原来这里还有一个 `log_context_budget`，只统计各来源 token 数、不区分是否被
裁剪/丢弃（P3 第一阶段）。两个 Agent 的调用点已经升级为 `app/context/manifest.py`
的 `log_context_manifest`，输出更完整的上下文清单（含 included/truncated/
drop_reason），这个模块现在只保留最基础的计数原语，供 manifest 复用。
"""
from __future__ import annotations

import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str | None) -> int:
    if not text:
        return 0
    return len(_encoding.encode(text))
