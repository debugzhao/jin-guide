"""
FastAPI 公共依赖。

get_current_user    — 从 session_token cookie 解析出 User（未登录则返回 None）
require_auth        — 未登录时抛 401
require_admin_role  — 非管理员时抛 403
get_identity         — 从 session_token cookie 解析出 (User | None, anonymous_id | None)，
                       同时覆盖已登录和匿名会话两种请求场景
"""
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import AuthSession, User


async def get_current_user(
    session_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """返回已认证的 User；匿名请求返回 None。"""
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
    """请求没有有效 session 时抛 401。"""
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录")
    return current_user


async def require_admin_role(
    current_user: User | None = Depends(get_current_user),
) -> User:
    """当前用户不是管理员时抛 403。"""
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
    从 session_token cookie 解析请求方身份——可能是已登录的 User、
    一个 anonymous_id（匿名会话），或两者都不是。
    供那些按"当前用户或匿名会话"划分数据范围的接口使用（例如报告历史），
    这些接口不强制要求完整登录。
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


def get_client_ip(request: Request) -> str:
    """
    尽力获取客户端 IP，用于按 IP 限流（例如建档前聊天的匿名兜底限流——
    docs/backend-prd-v2.md §11.4）。优先读取 X-Forwarded-For（由 API 前面的
    nginx 反向代理设置），本地/直连请求时回退到原始 peer 地址。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
