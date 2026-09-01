"""
ConversationStore —— IntakeAgent（intake_chat.py）和 ConversationAgent（chat.py）
共用的 Redis + PostgreSQL 对话历史持久化基础设施。

在这个模块出现之前，两个调用方各自手搓了几乎一样的逻辑，且逐渐跑偏（两个接口的
匿名身份 key 格式不一致、DB 写失败被静默吞掉、没有并发控制）——详见
docs/memory-architecture.md §六 P0。本模块统一承担：

- owner_key(identity)：一段记忆归属于谁（真实用户 id，或 anon:{anonymous_id}）。
  thread_id（LangGraph 执行 id）是另一个维度——它标识的是一次报告生成的运行，
  不是一个人——这里绝不能用它。
- Postgres 是唯一权威存储；Redis 只是可随时丢弃的低延迟缓存，可能悄悄与
  Postgres 不一致（TTL 过期、内存压力、或某次 DB 写入失败）。两层都要防并发
  追加互相踩踏：Redis 用服务端 Lua 脚本（原子执行，完全没有客户端竞态窗口——
  最初试过客户端 WATCH/MULTI 重试循环，在真实并发下依然会丢消息，见 git
  历史），Postgres 用 version_id_col 乐观锁 + 重试。

本模块有意只做一组基础原语，不做大而全的 MemoryManager——每个接口仍然自己管理
各自的 schema 查询/写入形态（IntakeConversation 是多会话+软删除，
ReportConversation 是每个 report+owner 一行）；只把"不能再次跑偏"的机制收敛
到这里。
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Callable
from uuid import uuid4

import redis.asyncio as aioredis
import structlog
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.api.dependencies import Identity
from app.config import settings
from app.models.conversation import ConversationMessage, ConversationSummary

logger = structlog.get_logger()

HISTORY_TTL_SECONDS = 7 * 24 * 3600  # 7 天
MAX_MESSAGES_STORED = 50
_MAX_DB_LOCK_RETRIES = 5
_MAX_SEQ_RETRIES = 5

# 生成过程中把已产出的部分内容同步进 Postgres/Redis 的节流间隔——见
# append_conversation_messages/update_message_content 的"生成开始建空记录"设计。
# 每个 token 都落库成本太高，按时间节流成一个"哪怕刷新页面也最多丢几百毫秒
# 内容"的折中。
INCREMENTAL_FLUSH_INTERVAL_SECONDS = 1.0

# 把 `to_append`（JSON 数组，ARGV[1]）原子地追加到 KEYS[1] 存的列表末尾，
# 裁剪到最近 ARGV[2] 条，并重设 TTL——全部在一次服务端 EVAL 里完成，完全没有
# 客户端"读-改-写"竞态窗口。最初的实现用的是 Redis WATCH/MULTI 重试循环，
# 重试 N 次仍失败后再无保护地强写；真实并发下（~20 个请求同时追加同一个
# key）大量请求同时耗尽重试次数，它们的无保护强写又互相覆盖，悄悄丢消息——
# 这正是本脚本要修复的 bug。Lua 脚本没有这个窗口，因为 Redis 把它当作一次
# 原子操作整体执行。
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

# 原地原子修改 KEYS[1] 存的列表中最后一个元素——只改它的 `content`
# （以及 ARGV[2] 非空时的 `citations`）——其余元素和字段原样不动。用来让
# Redis 热缓存跟上 append_conversation_messages/update_message_content 写入的
# "先建空记录再逐步填充"助手占位行（见"生成开始建空记录"——
# docs/疑问杂项.md「生成过程中刷新页面丢失聊天记录」）：token 流式返回时，
# 每次节流刷新只原子修改这一个字段，因此并发读者（比如用户正好在这时刷新页面
# 触发 GET history）永远不会看到写了一半的数组——Redis 把整段脚本当一次操作
# 执行，和上面 _APPEND_AND_TRIM_LUA 是同一种保证。
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


# ── 身份 ─────────────────────────────────────────────────────────────────────

def owner_key(identity: Identity) -> str | None:
    """真实用户 id；匿名会话则返回 anon:{anonymous_id}；请求既没有登录
    session 也没有匿名 session 时返回 None。"""
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


# ── 限流 ─────────────────────────────────────────────────────────────────────

def rate_limit_key(namespace: str, key: str) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    return f"{namespace}:daily:{key}:{today}"


async def check_and_increment_rate_limit(namespace: str, key: str) -> int:
    """给 `key` 今天的消息计数器加一，返回加完之后的计数值。"""
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


# ── Redis 历史（热层，原子写）───────────────────────────────────────────────

def history_key(namespace: str, *parts: str) -> str:
    return f"{namespace}:history:" + ":".join(parts)


def _normalize_citations(messages: list[dict]) -> list[dict]:
    """
    Lua 的 cjson 区分不了空数组和空对象——任何带 `citations: []` 的消息经过
    _APPEND_AND_TRIM_LUA/_UPDATE_LAST_MESSAGE_LUA 脚本内部的解码再编码后，
    都会变成 `citations: {}`。前端始终把 `citations` 当数组用
    （`.find()`/`.map()`），拿到 `{}` 会在渲染时直接报错——统一在这一处
    （所有 Redis 读取的唯一必经之路）把它纠正回 `[]`，而不是让每个调用方
    各自处理。
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
    把 `new_messages` 原子追加到 `key` 存的列表（通过服务端 Lua 脚本，见
    _APPEND_AND_TRIM_LUA），并裁剪到 MAX_MESSAGES_STORED 条。无论同一个 key
    同时来多少个并发追加请求，彼此都不会互相踩踏。返回追加后的完整历史。
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
    update_message_content 在 Redis 侧的对应实现：原子修改缓存历史数组里的
    最后一个元素（通过 _UPDATE_LAST_MESSAGE_LUA），让热缓存跟上 Postgres
    刚写入的同一段部分内容，且从不向并发读者暴露写了一半的数组。
    `citations=None` 表示"不动它"的约定和 update_message_content 一致。
    这是尽力而为——这里失败只意味着下一次 GET history 会回落读取
    Postgres（已经是最新的）副本，和任何其他 Redis 未命中情况一样。
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


# ── 重复/相似问题去重 ─────────────────────────────────────────────────────────
#
# 对已加载的历史做纯文本匹配——不调 embedding，不引入新的 Redis 结构。低成本
# 拦住意外的重复提问（重试、复制粘贴重新问一遍）；有意不做语义改写检测，因为
# 那意味着每条消息都要付一次 embedding 调用成本，只为防住少数重复场景
# （见 docs/backend-prd-v2.md §11.4）。

_TRAILING_PUNCTUATION = "。.!！?？，,、~～ "


def _normalize_question(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)  # 全角/半角、大小写变体统一
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.rstrip(_TRAILING_PUNCTUATION)
    return normalized.lower()


def find_cached_answer(
    history: list[dict],
    message: str,
    *,
    window_minutes: int,
    similarity_threshold: float,
) -> dict | None:
    """
    在 `history` 里查找最近（window_minutes 分钟内）一条用户消息，归一化后与
    `message` 完全相同或高度相似。命中且对应助手回复内容非空时才返回
    （content + citations，如果有），供调用方直接复用、完全跳过 LLM 调用——
    还在生成中的占位消息（内容为空）永远不会匹配，所以正在进行中的重复请求
    总会落到重新调用 LLM 这条路径。从最新往最旧扫描，命中的是最新的那次回答。
    """
    normalized_new = _normalize_question(message)
    if not normalized_new:
        return None
    cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
    for i in reversed(range(len(history))):
        msg = history[i]
        if msg.get("role") != "user":
            continue
        created_at = msg.get("created_at")
        if not created_at:
            continue
        try:
            ts = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        normalized_old = _normalize_question(msg.get("content", ""))
        if not normalized_old:
            continue
        matched = normalized_old == normalized_new
        if not matched:
            matched = SequenceMatcher(None, normalized_old, normalized_new).ratio() >= similarity_threshold
        if not matched:
            continue
        if i + 1 < len(history) and history[i + 1].get("role") == "assistant":
            answer = history[i + 1]
            if answer.get("content"):
                return answer
    return None


# ── PostgreSQL（权威冷层，乐观锁）───────────────────────────────────────────

async def get_or_create_conversation_row(
    db: AsyncSession,
    *,
    model_cls: type,
    match: tuple,
    make_new_row: Callable[[], object],
    log_context: dict,
) -> str | None:
    """
    查找或创建父级 ReportConversation/IntakeConversation 行，并刷新
    `updated_at`。消息内容本身存在 ConversationMessage 里（见下面
    append_conversation_messages）——这个函数只管父行的存在性和新鲜度，不再
    经手消息内容（见 P2 切换，docs/memory-architecture.md §六 P2，取代了这里
    原来"整体读数组→追加→整体覆盖写"的旧行为）。

    两个 model 都还声明了 `version_id_col`，所以每次 ORM UPDATE——即便只是
    改 `updated_at`——都会被乐观锁保护；因此这里保留重试循环。持久化失败会
    带上足够的上下文记日志方便排查，但不会向上抛给调用方（一次尽力而为的
    父行记账失败，不该导致聊天回复本身失败）。

    成功时返回该行的 `id`（已存在的或新建的）；重试后仍失败则返回 None。
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
            # 和另一个并发写入者的乐观锁竞争输了——回滚后针对当前最新的行
            # 重试，而不是直接丢弃这次写入。
            await db.rollback()
            continue
        except Exception as exc:  # noqa: BLE001 - 尽力而为的持久化，不能让异常向上冒泡导致聊天回复失败
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


# ── ConversationMessage（只追加存储，P2）───────────────────────────────────
#
# 用按单调递增 `seq` 每条消息单独一次 INSERT，取代旧的"整体读 messages_json
# 数组→追加→整体覆盖写"模式（见 docs/memory-architecture.md §六 P2）。
# 所有消息内容现在都存在这里——上面的 get_or_create_conversation_row 只管
# 父行的存在性/updated_at，完全不再经手消息内容。
#
# 下面每个函数都接收 `parent_kind: "report" | "intake"`，而不是直接传原始
# column 对象。ConversationMessage 和 ConversationSummary 各自有同名的
# report_conversation_id/intake_conversation_id 列——如果只传"report 那一列"
# 而不说明它属于哪个 model，很容易在不知不觉中用错 model 的列过滤查询
# （SQLAlchemy 不会报错，只会把另一张表悄悄加进 FROM 变成意外的交叉连接）。
# 让每个函数自己根据 `parent_kind` 去解析出属于自己 model 的那一列，从结构上
# 杜绝这种错误。
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
    把 `new_messages` 逐条插入为独立的行。因为每条消息都是各自的 INSERT，
    两个并发写入者只可能在 `seq` 唯一约束上撞车——绝不会撞在消息内容上——
    所以冲突只需要重新计算下一个 seq 再重试即可，不像旧的整体覆盖写路径，
    输的那一方的消息会被静默丢弃。

    成功时返回插入行的 id 列表（顺序与 `new_messages` 一致），重试后仍失败
    则返回 None。调用方如果在用户消息旁边插入了一个空的助手占位行（见"生成
    开始建空记录"——docs/疑问杂项.md「生成过程中刷新页面丢失聊天记录」），
    会拿 `ids[-1]` 配合下面的 update_message_content，随着回复流式返回逐步
    填充内容，而不是只在最后一次性写入。
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
            # 和另一个并发写入者的 seq 竞争输了——回滚后按当前最新的最大值
            # 重新计算 next_seq 再重试。
            await db.rollback()
            continue
        except Exception as exc:  # noqa: BLE001 - 尽力而为的持久化，不能让异常向上冒泡导致聊天回复失败
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
    按 id 原地更新一行 ConversationMessage 的 content（可选同时更新
    citations）——这是"生成开始建空记录，逐步填充"方案里"逐步填充"的那一半
    （docs/疑问杂项.md「生成过程中刷新页面丢失聊天记录」）：这一行在流式开始
    前已经通过 append_conversation_messages 插入（内容为空），这里只是随着
    token 到达不断重绘它。不需要乐观锁重试——和 report_conversations/
    intake_conversations 不同，ConversationMessage 没有 version_id_col，
    也只有创建这一行的那个请求会去更新它。

    `citations` 传 `None` 表示"维持现状不动"（逐 token 节流刷新时还不知道
    citations 是什么），传显式列表——即便是 `[]`——表示"设置它"（在完整回复
    抽取出 citations 之后、`done` 时刻的最终一次刷新）。

    尽力而为：失败只记日志、不向上抛，和本模块里其他持久化原语一致——流式
    过程中一次内容同步的小故障，不该表现为一次聊天错误。
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
    except Exception as exc:  # noqa: BLE001 - 尽力而为的持久化，不能让异常向上冒泡导致聊天回复失败
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
    冷路径读取（Redis 未命中时）——从权威的 conversation_messages 表读取，
    取代旧的读 messages_json 列的方式。按时间顺序返回最近 `limit` 条消息。
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


# ── ConversationSummary（结构化增量摘要，P2）────────────────────────────────

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
    expected_covered_through_seq: int,
    source_model: str,
    prompt_version: str,
    tokens_before: int | None,
    tokens_after: int | None,
    status: str = "ready",
) -> None:
    """
    为一个会话创建或更新唯一的 ConversationSummary 行。只应由尽力而为的后台
    摘要生成任务调用（见 conversation_summary.py）——这里持久化失败只记日志、
    不能向上抛，因为调用方早已决定好失败时是保留旧摘要不动、还是把这次尝试
    记为失败。

    `expected_covered_through_seq` 是调用方在开始生成前读到的旧
    `covered_through_seq`（没有旧摘要时为 0）。更新按它做一次数据库层面的
    CAS（`WHERE covered_through_seq = :expected`）：如果这期间已经有另一个
    并发的后台任务先一步写入了更新的摘要，`covered_through_seq` 已经变了，
    这里检测到 0 行受影响就直接放弃，不会用自己这次算出的、基于旧摘要生成
    的结果覆盖别人已提交的新结果，也不会让 `covered_through_seq` 倒退。
    调用方（conversation_summary.py）额外用 Redis 锁把整个生成流程串行化，
    这里是锁失效（TTL 到期、Redis 重启等）时的最后一道保险，两者共同防止
    "旧摘要覆盖新摘要"的并发写丢失问题。
    """
    parent_column = _SUMMARY_PARENT_COLUMNS[parent_kind]
    parent_kwarg = parent_column.key
    try:
        existing = await load_summary(db, parent_kind=parent_kind, parent_id=parent_id)
        if existing:
            result = await db.execute(
                update(ConversationSummary)
                .where(
                    ConversationSummary.id == existing.id,
                    ConversationSummary.covered_through_seq == expected_covered_through_seq,
                )
                .values(
                    summary_json=summary_json,
                    covered_through_seq=covered_through_seq,
                    summary_version=ConversationSummary.summary_version + 1,
                    source_model=source_model,
                    prompt_version=prompt_version,
                    tokens_before=tokens_before,
                    tokens_after=tokens_after,
                    status=status,
                    updated_at=datetime.now(UTC),
                )
            )
            if result.rowcount == 0:
                await db.rollback()
                logger.info(
                    "conversation_summary_cas_conflict",
                    expected_covered_through_seq=expected_covered_through_seq,
                    **{parent_kwarg: parent_id},
                )
                return
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
    except IntegrityError:
        # 两个并发任务都判断"还没有摘要行"→都走 INSERT，唯一约束让后提交
        # 的一方在这里失败——对方已经创建了权威的第一份摘要，这次直接放弃。
        await db.rollback()
        logger.info("conversation_summary_cas_conflict_on_insert", **{parent_kwarg: parent_id})
    except Exception as exc:  # noqa: BLE001 - 尽力而为的持久化，不能让异常向上冒泡导致聊天回复失败
        await db.rollback()
        logger.warning(
            "conversation_summary_persist_failed", error=str(exc), **{parent_kwarg: parent_id}
        )
