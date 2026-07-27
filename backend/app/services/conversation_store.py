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
from uuid import uuid4

import redis.asyncio as aioredis
import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.api.dependencies import Identity
from app.config import settings
from app.models.conversation import ConversationMessage, ConversationSummary

logger = structlog.get_logger()

HISTORY_TTL_SECONDS = 7 * 24 * 3600  # 7 days
MAX_MESSAGES_STORED = 50
_MAX_DB_LOCK_RETRIES = 5
_MAX_SEQ_RETRIES = 5

# 生成过程中把已产出的部分内容同步进 Postgres/Redis 的节流间隔——见
# append_conversation_messages/update_message_content 的"生成开始建空记录"设计。
# 每个 token 都落库成本太高，按时间节流成一个"哪怕刷新页面也最多丢几百毫秒
# 内容"的折中。
INCREMENTAL_FLUSH_INTERVAL_SECONDS = 1.0

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

# Atomically patch the LAST element of the list stored at KEYS[1] in place —
# only its `content` (and `citations`, if ARGV[2] is non-empty) — leaving
# every other element and field untouched. Used to keep the Redis hot cache
# in sync with the empty-then-filled-in assistant placeholder row written by
# append_conversation_messages/update_message_content (see "生成开始建空记录"
# — docs/疑问杂项.md「生成过程中刷新页面丢失聊天记录」): as tokens stream in,
# each throttled flush patches just this one field atomically, so a
# concurrent reader (e.g. GET history right as the user refreshes) can never
# observe a half-written array — Redis executes the whole script as one
# operation, same guarantee as _APPEND_AND_TRIM_LUA above.
_UPDATE_LAST_MESSAGE_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local ok, current = pcall(cjson.decode, raw)
if not ok or #current == 0 then
  return 0
end
local last = current[#current]
last['content'] = ARGV[1]
if ARGV[2] ~= '' then
  local ok2, decoded = pcall(cjson.decode, ARGV[2])
  if ok2 then
    last['citations'] = decoded
  end
end
current[#current] = last
local result = cjson.encode(current)
redis.call('SETEX', KEYS[1], ARGV[3], result)
return 1
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


def _normalize_citations(messages: list[dict]) -> list[dict]:
    """
    Lua's cjson can't tell an empty array from an empty object — any message
    dict that passed through _APPEND_AND_TRIM_LUA/_UPDATE_LAST_MESSAGE_LUA with
    `citations: []` comes back out as `citations: {}` after the
    decode-then-re-encode round trip inside the script. The frontend always
    treats `citations` as an array (`.find()`/`.map()`), so `{}` would throw
    at render time — normalize it back to `[]` here, at the single point every
    Redis read passes through, rather than in every caller.
    """
    for msg in messages:
        if isinstance(msg.get("citations"), dict) and not msg["citations"]:
            msg["citations"] = []
    return messages


async def load_history_from_redis(key: str) -> list[dict]:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis_client.get(key)
        return _normalize_citations(json.loads(raw)) if raw else []
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


async def update_last_message_content_in_redis(
    key: str, content: str, citations: list | None = None
) -> None:
    """
    Redis-side counterpart to update_message_content: atomically patch the
    LAST element of the cached history array (via _UPDATE_LAST_MESSAGE_LUA)
    so the hot cache reflects the same partial content Postgres just got,
    without ever exposing a half-written array to a concurrent reader. Same
    `citations=None` "leave it alone" convention as update_message_content.
    Best-effort — a failure here just means the next GET history falls back
    to Postgres's (already-updated) copy, exactly like any other Redis miss.
    """
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.eval(
            _UPDATE_LAST_MESSAGE_LUA,
            1,
            key,
            content,
            json.dumps(citations, ensure_ascii=False) if citations is not None else "",
            HISTORY_TTL_SECONDS,
        )
    except Exception:
        logger.warning("conversation_redis_update_last_failed", key=key)
    finally:
        await redis_client.aclose()


async def delete_history_from_redis(key: str) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.delete(key)
    finally:
        await redis_client.aclose()


# ── PostgreSQL (authoritative cold layer, optimistic locking) ───────────────

async def get_or_create_conversation_row(
    db: AsyncSession,
    *,
    model_cls: type,
    match: tuple,
    make_new_row: Callable[[], object],
    log_context: dict,
) -> str | None:
    """
    Find-or-create the parent ReportConversation/IntakeConversation row and
    touch `updated_at`. Message content itself lives in ConversationMessage
    (see append_conversation_messages below) — this only manages the parent
    row's existence and freshness, no longer message content (see P2 cutover,
    docs/memory-architecture.md §六 P2, which replaced the previous
    read-whole-array-append-overwrite behavior here).

    Both models still declare `version_id_col`, so every ORM UPDATE — even
    just `updated_at` — is optimistic-locked; kept as a retry loop for that
    reason. A persist failure is logged with enough context to investigate,
    while still not raising to the caller (a chat reply must not fail just
    because the best-effort parent-row bookkeeping did).

    Returns the row's `id` (existing or newly created) on success, or None if
    the persist failed after retries.
    """
    for attempt in range(_MAX_DB_LOCK_RETRIES):
        try:
            result = await db.execute(select(model_cls).where(*match))
            conv = result.scalar_one_or_none()
            if conv:
                conv.updated_at = datetime.now(UTC)
                row_id = conv.id
            else:
                new_row = make_new_row()
                db.add(new_row)
                row_id = new_row.id
            await db.commit()
            return row_id
        except StaleDataError:
            # Lost the optimistic-lock race against a concurrent writer —
            # roll back and retry against the now-current row instead of
            # dropping this write.
            await db.rollback()
            continue
        except Exception as exc:  # noqa: BLE001 - best-effort persistence must not crash the reply
            await db.rollback()
            logger.warning(
                "conversation_row_persist_failed",
                model=model_cls.__name__,
                error=str(exc),
                attempt=attempt,
                **log_context,
            )
            return None
    logger.warning(
        "conversation_row_optimistic_lock_exhausted",
        model=model_cls.__name__,
        **log_context,
    )
    return None


# ── ConversationMessage (append-only store, P2) ─────────────────────────────
#
# Replaces the old "read whole messages_json array → append → overwrite"
# pattern with one INSERT per message under a monotonically increasing `seq`
# (see docs/memory-architecture.md §六 P2). All message content lives here now
# — get_or_create_conversation_row above only manages the parent row's
# existence/updated_at, it no longer touches message content at all.
#
# Every function below takes a `parent_kind: "report" | "intake"` instead of
# a raw column object. ConversationMessage and ConversationSummary each have
# their own report_conversation_id/intake_conversation_id columns with the
# same names — passing "the report column" without saying which model it
# belongs to is an easy way to silently filter one model's query by another
# model's column (SQLAlchemy just adds the other table to FROM as an
# unintended cross join instead of raising). Resolving the column from
# `parent_kind` inside each function, against that function's own model,
# makes that mistake structurally impossible.
_MESSAGE_PARENT_COLUMNS = {
    "report": ConversationMessage.report_conversation_id,
    "intake": ConversationMessage.intake_conversation_id,
}
_SUMMARY_PARENT_COLUMNS = {
    "report": ConversationSummary.report_conversation_id,
    "intake": ConversationSummary.intake_conversation_id,
}


async def append_conversation_messages(
    db: AsyncSession,
    *,
    parent_kind: str,
    parent_id: str,
    new_messages: list[dict],
    log_context: dict,
) -> list[str] | None:
    """
    Append `new_messages` as individual rows. Because each message is its own
    INSERT, two concurrent writers can only collide on the `seq` unique
    constraint — never on message content — so a conflict just means
    recomputing the next seq and retrying, unlike the old array-overwrite
    path where the loser's messages were silently dropped.

    Returns the inserted rows' ids, in the same order as `new_messages`, on
    success, or None if persistence failed after retries. Callers that insert
    an empty assistant placeholder alongside the user message (see "生成开始
    建空记录" — docs/疑问杂项.md「生成过程中刷新页面丢失聊天记录」) use
    `ids[-1]` with update_message_content below to fill it in incrementally
    as the response streams in, instead of only writing once at the end.
    """
    if not new_messages:
        return None
    parent_column = _MESSAGE_PARENT_COLUMNS[parent_kind]
    parent_kwarg = parent_column.key
    for attempt in range(_MAX_SEQ_RETRIES):
        try:
            result = await db.execute(
                select(func.max(ConversationMessage.seq)).where(parent_column == parent_id)
            )
            next_seq = (result.scalar() or 0) + 1
            inserted_ids: list[str] = []
            for offset, msg in enumerate(new_messages):
                created_at = msg.get("created_at")
                row_id = str(uuid4())
                db.add(
                    ConversationMessage(
                        id=row_id,
                        **{parent_kwarg: parent_id},
                        seq=next_seq + offset,
                        role=msg["role"],
                        content=msg["content"],
                        citations=msg.get("citations"),
                        created_at=(
                            datetime.fromisoformat(created_at)
                            if created_at
                            else datetime.now(UTC)
                        ),
                    )
                )
                inserted_ids.append(row_id)
            await db.commit()
            return inserted_ids
        except IntegrityError:
            # Lost the seq race against a concurrent writer — roll back and
            # recompute next_seq against the now-current max before retrying.
            await db.rollback()
            continue
        except Exception as exc:  # noqa: BLE001 - best-effort persistence must not crash the reply
            await db.rollback()
            logger.warning(
                "conversation_message_persist_failed",
                error=str(exc),
                attempt=attempt,
                **log_context,
            )
            return None
    logger.warning("conversation_message_seq_retries_exhausted", **log_context)
    return None


async def update_message_content(
    db: AsyncSession,
    *,
    message_id: str,
    content: str,
    citations: list | None = None,
) -> bool:
    """
    Update one ConversationMessage row's content (and optionally citations)
    in place by id — the incremental-fill half of "生成开始建空记录，逐步填充"
    (docs/疑问杂项.md「生成过程中刷新页面丢失聊天记录」): the row itself was
    already inserted (empty content) via append_conversation_messages before
    streaming started, this just repaints it as tokens arrive. No
    optimistic-lock retry needed — unlike report_conversations/
    intake_conversations, ConversationMessage carries no version_id_col and
    only the request that created a given row ever updates it.

    `citations` is `None` to mean "leave whatever is already there" (the
    incremental per-token flush never knows citations yet) vs an explicit
    list — even `[]` — to mean "set it" (the final flush at `done`, once
    citations have been extracted from the complete response).

    Best-effort: a failure is logged but never raised, matching every other
    persistence primitive in this module — a content-sync hiccup mid-stream
    must not surface as a chat error.
    """
    try:
        result = await db.execute(select(ConversationMessage).where(ConversationMessage.id == message_id))
        row = result.scalar_one_or_none()
        if not row:
            return False
        row.content = content
        if citations is not None:
            row.citations = citations
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - best-effort persistence must not crash the reply
        await db.rollback()
        logger.warning("conversation_message_update_failed", message_id=message_id, error=str(exc))
        return False


async def load_recent_messages_from_db(
    db: AsyncSession,
    *,
    parent_kind: str,
    parent_id: str,
    limit: int = MAX_MESSAGES_STORED,
) -> list[dict]:
    """
    Cold-path read (Redis miss) from the authoritative conversation_messages
    table — replaces reading the legacy messages_json column. Returns the
    most recent `limit` messages in chronological order.
    """
    parent_column = _MESSAGE_PARENT_COLUMNS[parent_kind]
    result = await db.execute(
        select(ConversationMessage)
        .where(parent_column == parent_id)
        .order_by(ConversationMessage.seq.desc())
        .limit(limit)
    )
    rows = list(reversed(result.scalars().all()))
    messages = []
    for row in rows:
        msg = {
            "role": row.role,
            "content": row.content,
            "created_at": row.created_at.isoformat(),
        }
        if row.citations is not None:
            msg["citations"] = row.citations
        messages.append(msg)
    return messages


# ── ConversationSummary (structured incremental summary, P2) ───────────────

async def load_summary(
    db: AsyncSession, *, parent_kind: str, parent_id: str
) -> ConversationSummary | None:
    parent_column = _SUMMARY_PARENT_COLUMNS[parent_kind]
    result = await db.execute(select(ConversationSummary).where(parent_column == parent_id))
    return result.scalar_one_or_none()


async def upsert_summary(
    db: AsyncSession,
    *,
    parent_kind: str,
    parent_id: str,
    summary_json: dict,
    covered_through_seq: int,
    source_model: str,
    prompt_version: str,
    tokens_before: int | None,
    tokens_after: int | None,
    status: str = "ready",
) -> None:
    """
    Create or update the single ConversationSummary row for a conversation.
    Only called from the best-effort background summarization task (see
    conversation_summary.py) — a persist failure here is logged but must not
    raise, since the caller already decided whether to keep the previous
    summary untouched or record this attempt as failed.
    """
    parent_column = _SUMMARY_PARENT_COLUMNS[parent_kind]
    parent_kwarg = parent_column.key
    try:
        existing = await load_summary(db, parent_kind=parent_kind, parent_id=parent_id)
        if existing:
            existing.summary_json = summary_json
            existing.covered_through_seq = covered_through_seq
            existing.summary_version += 1
            existing.source_model = source_model
            existing.prompt_version = prompt_version
            existing.tokens_before = tokens_before
            existing.tokens_after = tokens_after
            existing.status = status
            existing.updated_at = datetime.now(UTC)
        else:
            db.add(
                ConversationSummary(
                    **{parent_kwarg: parent_id},
                    summary_json=summary_json,
                    covered_through_seq=covered_through_seq,
                    source_model=source_model,
                    prompt_version=prompt_version,
                    tokens_before=tokens_before,
                    tokens_after=tokens_after,
                    status=status,
                )
            )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - best-effort persistence must not crash the reply
        await db.rollback()
        logger.warning(
            "conversation_summary_persist_failed", error=str(exc), **{parent_kwarg: parent_id}
        )
