"""
Token 计数与上下文预算快照——见 docs/memory-architecture.md 第六节 P3 第一阶段。

只做观测，不做任何截断/裁剪决策。目的是先量化"现在每次请求实际往 Prompt 里
塞了多少 token、分别来自哪个上下文来源、有没有被截断过"，为后续要不要做统一
Context Builder（以及怎么设计）提供真实数据，而不是凭感觉判断。

跟 LangSmith 的分工：LangSmith（已通过 litellm_config.yaml 的 success_callback
接好）能看到每次调用的真实总 token 数和成本趋势，但看不到"这些 token 里哪部分
来自证据、哪部分来自历史"——这个语义归因只存在于组装 Prompt 的代码里，一旦拼成
扁平的 messages 数组发出去就丢失了，所以这部分必须在这里算，不能指望 LangSmith
替代（详见 docs/疑问杂项.md）。

Token 数用 tiktoken 的 cl100k_base 编码近似估算——kimi-k2.6 没有公开的官方
tokenizer，这里只需要同一次请求内不同来源之间的相对比较，不需要字节级精确；
真实精确值可以从 LangSmith 里查每次调用的 usage 字段。

用 structlog 而不是调用方各自的 `logging.getLogger(__name__)`：这两个 Agent
文件目前用的是 stdlib logging，其 logger 有效级别继承自 root（默认 WARNING），
`logger.info(...)` 会被静默丢弃、docker logs 里根本看不到——`app/logging_config.py`
配置的是 structlog 的过滤级别（INFO），只有通过 `structlog.get_logger()` 拿到的
logger 才会真正被这层配置管到。这里直接内置一个 structlog logger，调用方不需要
关心这个细节。
"""
from __future__ import annotations

import structlog
import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")
_logger = structlog.get_logger()


def count_tokens(text: str | None) -> int:
    if not text:
        return 0
    return len(_encoding.encode(text))


def log_context_budget(
    *,
    agent: str,
    sources: dict[str, str],
    truncated: dict[str, bool] | None = None,
) -> None:
    """
    统计 `sources` 里每个上下文来源的 token 数并打一条结构化日志。

    `sources`：{来源名: 实际拼进 Prompt 的文本}，比如
    `{"plan_json": "...", "evidence": "...", "history": "...", "summary": "..."}`。
    `truncated`：标记哪些来源在拼装前就已经被字符数/条数截断过（只传发生了截断
    的来源即可，未提及的视为未截断）。
    """
    token_usage = {key: count_tokens(text) for key, text in sources.items()}
    _logger.info(
        "context_budget_snapshot",
        agent=agent,
        total_tokens=sum(token_usage.values()),
        breakdown=token_usage,
        truncated=truncated or {},
    )
