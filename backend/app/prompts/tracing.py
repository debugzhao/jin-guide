from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from app.prompts.models import PromptSpec

logger = logging.getLogger(__name__)

_ALLOWED_CONTEXT_KEYS = frozenset({"agent_run_id", "report_id", "conversation_id", "parent_kind"})


@dataclass
class PromptInvocationTrace:
    invocation_id: str
    spec: PromptSpec
    context: dict[str, str]

    def request_options(self) -> dict:
        return self.spec.request_options(invocation_id=self.invocation_id, **self.context)


@asynccontextmanager
async def track_prompt_invocation(spec: PromptSpec, **context: str | None):
    """记录调用版本、耗时和状态；审计库故障不能影响用户主链路。"""
    safe_context = {
        key: str(value)
        for key, value in context.items()
        if key in _ALLOWED_CONTEXT_KEYS and value
    }
    trace = PromptInvocationTrace(str(uuid4()), spec, safe_context)
    started_at = time.perf_counter()
    status = "success"
    error_type: str | None = None
    try:
        yield trace
    except Exception as exc:
        status = "failed"
        error_type = type(exc).__name__
        raise
    finally:
        await _persist_trace(
            trace,
            status=status,
            error_type=error_type,
            latency_ms=max(0, round((time.perf_counter() - started_at) * 1000)),
        )


async def _persist_trace(
    trace: PromptInvocationTrace, *, status: str, error_type: str | None, latency_ms: int
) -> None:
    try:
        from app.database import async_session_maker
        from app.models.prompt_invocation import PromptInvocation

        async with async_session_maker() as db:
            db.add(
                PromptInvocation(
                    id=trace.invocation_id,
                    prompt_name=trace.spec.prompt_name,
                    prompt_version=trace.spec.version,
                    prompt_hash=trace.spec.content_hash,
                    model_alias=trace.spec.model.alias,
                    status=status,
                    latency_ms=latency_ms,
                    error_type=error_type,
                    context_json=trace.context or None,
                )
            )
            await db.commit()
    except Exception as exc:
        logger.warning("prompt invocation audit write failed: %s", exc)
