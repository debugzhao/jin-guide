"""
Shared FastAPI dependencies.

get_current_user    — resolve User from session_token cookie (or None)
require_auth        — 401 if not logged in
require_admin_role  — 403 if not admin
"""
from datetime import UTC, datetime

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import AuthSession, User


async def get_current_user(
    session_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the authenticated User or None for anonymous requests."""
    if not session_token:
        return None
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.id == session_token,
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    session = result.scalar_one_or_none()
    if not session or not session.user_id:
        return None
    user_result = await db.execute(select(User).where(User.id == session.user_id))
    return user_result.scalar_one_or_none()


async def require_auth(
    current_user: User | None = Depends(get_current_user),
) -> User:
    """Raise 401 if the request has no valid session."""
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录")
    return current_user


async def require_admin_role(
    current_user: User | None = Depends(get_current_user),
) -> User:
    """Raise 403 if the current user is not an admin."""
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录")
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user
