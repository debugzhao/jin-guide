"""
站内通知 API (docs/backend-prd-v2.md §5.1, §6.1)。

Endpoints:
  GET  /notifications            — 当前用户通知列表，游标分页
  POST /notifications/mark-read  — 标记通知为已读
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cursor import decode_cursor, encode_cursor
from app.api.dependencies import require_auth
from app.database import get_db
from app.models.notification import Notification
from app.models.user import User

router = APIRouter()


class NotificationOut(BaseModel):
    id: str
    type: str
    payload: Optional[dict]
    read_at: Optional[str]
    created_at: str


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    next_cursor: Optional[str]
    has_more: bool


class MarkReadIn(BaseModel):
    notification_ids: list[str]


class MarkReadOut(BaseModel):
    updated: int


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    cursor: Optional[str] = None,
    limit: int = 20,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Notification).where(Notification.user_id == current_user.id)

    if cursor:
        try:
            cur_created_at, cur_id = decode_cursor(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid cursor")
        stmt = stmt.where(
            (Notification.created_at < cur_created_at)
            | ((Notification.created_at == cur_created_at) & (Notification.id < cur_id))
        )

    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None

    return NotificationListOut(
        items=[
            NotificationOut(
                id=n.id,
                type=n.type,
                payload=n.payload_json,
                read_at=n.read_at.isoformat() if n.read_at else None,
                created_at=n.created_at.isoformat(),
            )
            for n in rows
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post("/mark-read", response_model=MarkReadOut)
async def mark_read(
    body: MarkReadIn,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(
            Notification.id.in_(body.notification_ids),
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None),
        )
    )
    rows = result.scalars().all()
    now = datetime.now(UTC)
    for n in rows:
        n.read_at = now
    await db.commit()
    return MarkReadOut(updated=len(rows))
