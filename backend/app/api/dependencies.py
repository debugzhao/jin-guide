"""
Shared FastAPI dependencies.

get_current_user    — resolve User from session_token cookie (or None)
require_auth        — 401 if not logged in
require_admin_role  — 403 if not admin
get_identity         — resolve (User | None, anonymous_id | None) from session_token cookie,
                       covers both logged-in and anonymous-session requests
"""
from dataclasses import dataclass
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


@dataclass
class Identity:
    user: User | None
    anonymous_id: str | None


async def get_identity(
    session_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> Identity:
    """
    Resolve the requester's identity from the session_token cookie —
    either a logged-in User, an anonymous_id (匿名会话), or neither.
    Used by endpoints that scope data to "the current user or anonymous session"
    (e.g. report history) instead of requiring a full login.
    """
    if not session_token:
        return Identity(user=None, anonymous_id=None)
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.id == session_token,
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return Identity(user=None, anonymous_id=None)
    if session.user_id:
        user_result = await db.execute(select(User).where(User.id == session.user_id))
        return Identity(user=user_result.scalar_one_or_none(), anonymous_id=None)
    return Identity(user=None, anonymous_id=session.anonymous_id)
