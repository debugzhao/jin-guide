"""
ConversationStore — shared Redis + PostgreSQL persistence primitives for
chat-style conversation history, used by both IntakeAgent (intake_chat.py)
and ConversationAgent (chat.py).

Before this module existed, the two call sites hand-rolled near-identical
logic independently and drifted apart (different anonymous-identity key
shapes between endpoints, silently-swallowed DB write failures, no
concurrency control) — see docs/memory-architecture.md §六 P0. This module
is the single source of truth for:

- owner_key(identity): who a piece of memory belongs to (real user id, or
  anon:{anonymous_id}). thread_id (LangGraph execution id) is a different
  axis — it identifies one report-generation run, not a person — and must
  never be used here.
- Postgres is the sole authoritative store; Redis is a disposable low-latency
  cache that may silently diverge (TTL eviction, memory pressure, or a failed
  DB write). Both layers guard against concurrent appends: Redis via a
  server-side Lua script (atomic, no client-side race window at all — a
  client-side WATCH/MULTI retry loop was tried first and still lost messages
  under real concurrency, see git history), Postgres via version_id_col
  optimistic locking with retry.

This intentionally stays a set of primitives, not a do-everything
MemoryManager — each endpoint still owns its own schema-specific query/insert
shape (IntakeConversation is multi-session + soft-delete, ReportConversation
is one row per report+owner); only the mechanics that must not diverge again
are centralized here.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Callable

import redis.asyncio as aioredis
import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.api.dependencies import Identity
from app.config import settings

logger = structlog.get_logger()

HISTORY_TTL_SECONDS = 7 * 24 * 3600  # 7 days
MAX_MESSAGES_STORED = 50
_MAX_DB_LOCK_RETRIES = 5

# Atomically append `to_append` (JSON array, ARGV[1]) to the list stored at
# KEYS[1], trim to the last ARGV[2] entries, and re-set the TTL — all inside
# one server-side EVAL, so there is no client-side read-modify-write race
# window at all. A first attempt at this used a Redis WATCH/MULTI retry loop
# with a final "unguarded write" fallback after N failed attempts; under real
# concurrency (~20 simultaneous appends to one key) many requests exhausted
# their retries at the same time and their unguarded fallback writes raced
# each other too, silently dropping messages — exactly the bug this is meant
# to fix. A Lua script has no such window because Redis executes it as a
# single atomic operation.
_APPEND_AND_TRIM_LUA = """
local raw = redis.call('GET', KEYS[1])
local current = {}
if raw then
  current = cjson.decode(raw)
end
local to_append = cjson.decode(ARGV[1])
for i = 1, #to_append do
  table.insert(current, to_append[i])
end
local max_len = tonumber(ARGV[2])
if #current > max_len then
  local trimmed = {}
  local start_idx = #current - max_len + 1
  for i = start_idx, #current do
    table.insert(trimmed, current[i])
  end
  current = trimmed
end
local result = cjson.encode(current)
redis.call('SETEX', KEYS[1], ARGV[3], result)
return result
"""


# ── Identity ─────────────────────────────────────────────────────────────────

def owner_key(identity: Identity) -> str | None:
    """Real user id, or anon:{anonymous_id} for anonymous sessions, or None
    if the request carries neither a login session nor an anonymous one."""
    if identity.user:
        return identity.user.id
    if identity.anonymous_id:
        return f"anon:{identity.anonymous_id}"
    return None


def require_owner_key(identity: Identity) -> str:
    key = owner_key(identity)
    if not key:
        raise HTTPException(
            status_code=401,
            detail="需要先建立匿名会话或登录才能开始对话，请先调用 /auth/anonymous-session",
        )
    return key


# ── Rate limit ───────────────────────────────────────────────────────────────

def rate_limit_key(namespace: str, key: str) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    return f"{namespace}:daily:{key}:{today}"


async def check_and_increment_rate_limit(namespace: str, key: str) -> int:
    """Increment today's message counter for `key`. Returns the new count."""
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        rkey = rate_limit_key(namespace, key)
        count = await redis_client.incr(rkey)
        if count == 1:
            now = datetime.now(UTC)
            tomorrow = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            await redis_client.expire(rkey, int((tomorrow - now).total_seconds()))
        return count
    finally:
        await redis_client.aclose()


# ── Redis history (hot layer, CAS write) ────────────────────────────────────

def history_key(namespace: str, *parts: str) -> str:
    return f"{namespace}:history:" + ":".join(parts)


async def load_history_from_redis(key: str) -> list[dict]:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis_client.get(key)
        return json.loads(raw) if raw else []
    except Exception:
        return []
    finally:
        await redis_client.aclose()


async def append_history_to_redis(key: str, new_messages: list[dict]) -> list[dict]:
    """
    Atomically append `new_messages` to the list stored at `key` (via a
    server-side Lua script — see _APPEND_AND_TRIM_LUA) and trim to
    MAX_MESSAGES_STORED. Concurrent appends to the same key never race each
    other, regardless of how many arrive at the same time. Returns the full
    history after the append.
    """
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw_result = await redis_client.eval(
            _APPEND_AND_TRIM_LUA,
            1,
            key,
            json.dumps(new_messages, ensure_ascii=False),
            MAX_MESSAGES_STORED,
            HISTORY_TTL_SECONDS,
        )
        return json.loads(raw_result)
    except Exception:
        logger.warning("conversation_redis_append_failed", key=key)
        return new_messages
    finally:
        await redis_client.aclose()


async def delete_history_from_redis(key: str) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.delete(key)
    finally:
        await redis_client.aclose()


# ── PostgreSQL (authoritative cold layer, optimistic locking) ───────────────

async def upsert_conversation_row(
    db: AsyncSession,
    *,
    model_cls: type,
    match: tuple,
    build_new_messages: Callable[[list[dict]], list[dict]],
    make_new_row: Callable[[list[dict]], object],
    log_context: dict,
) -> None:
    """
    Optimistic-locked upsert shared by ReportConversation/IntakeConversation
    (both carry a `version_id_col` mapper arg). PostgreSQL is the
    authoritative store — a persist failure is no longer silently swallowed,
    it's logged with enough context to investigate, while still not raising
    to the caller (a chat reply must not fail just because the best-effort
    history write did).
    """
    for attempt in range(_MAX_DB_LOCK_RETRIES):
        try:
            result = await db.execute(select(model_cls).where(*match))
            conv = result.scalar_one_or_none()
            if conv:
                conv.messages_json = build_new_messages(conv.messages_json or [])[
                    -MAX_MESSAGES_STORED:
                ]
                conv.updated_at = datetime.now(UTC)
            else:
                db.add(make_new_row(build_new_messages([])[-MAX_MESSAGES_STORED:]))
            await db.commit()
            return
        except StaleDataError:
            # Lost the optimistic-lock race against a concurrent writer —
            # roll back and retry against the now-current row instead of
            # dropping this write.
            await db.rollback()
            continue
        except Exception as exc:  # noqa: BLE001 - best-effort persistence must not crash the reply
            await db.rollback()
            logger.warning(
                "conversation_db_persist_failed",
                model=model_cls.__name__,
                error=str(exc),
                attempt=attempt,
                **log_context,
            )
            return
    logger.warning(
        "conversation_db_optimistic_lock_exhausted",
        model=model_cls.__name__,
        **log_context,
    )
