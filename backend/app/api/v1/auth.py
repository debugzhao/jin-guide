"""
Auth API — email + password strategy.

Endpoints:
  POST /auth/send-code      — send 6-digit verification code to email (for registration)
  POST /auth/register       — register with email + code + password
  POST /auth/login          — login with email + password → set session cookie
  POST /auth/logout         — clear session cookie
  GET  /auth/me             — return current user info (requires session)
"""
import hashlib
import hmac
import random
import re
import string
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import AuthSession, User
from app.services.email import send_verification_code

logger = structlog.get_logger()
router = APIRouter()

_CODE_PREFIX = "auth:code:"
_CODE_TTL_MINUTES = 10
_CODE_TTL_SECONDS = _CODE_TTL_MINUTES * 60
_SESSION_DAYS = 30
_CODE_PATTERN = re.compile(r"^\d{6}$")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_password(password: str) -> str:
    """SHA-256 with SECRET_KEY as salt. For production use bcrypt/argon2."""
    return hashlib.sha256(
        settings.secret_key.encode() + password.encode()
    ).hexdigest()


def _verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(_hash_password(password), password_hash)


def _generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


async def _store_code(email: str, code: str) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.setex(f"{_CODE_PREFIX}{email}", _CODE_TTL_SECONDS, code)
    finally:
        await redis_client.aclose()


async def _get_stored_code(email: str) -> str | None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        return await redis_client.get(f"{_CODE_PREFIX}{email}")
    finally:
        await redis_client.aclose()


async def _delete_code(email: str) -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.delete(f"{_CODE_PREFIX}{email}")
    finally:
        await redis_client.aclose()


async def _verify_code(email: str, user_code: str) -> None:
    """Raise HTTPException if code is missing, expired, or mismatched."""
    normalized = user_code.strip()
    if not _CODE_PATTERN.match(normalized):
        raise HTTPException(status_code=400, detail="验证码格式不正确，应为 6 位数字")

    stored_code = await _get_stored_code(email)
    if not stored_code:
        raise HTTPException(status_code=400, detail="请先获取验证码，或验证码已过期")

    if not hmac.compare_digest(stored_code, normalized):
        raise HTTPException(status_code=400, detail="验证码不正确")


async def _send_email_code(email: str, code: str) -> bool:
    """Send verification code email via Resend. Returns whether email was actually sent."""
    return await send_verification_code(email, code, _CODE_TTL_MINUTES)


async def _get_current_user(
    session_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
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


# ── Schemas ─────────────────────────────────────────────────────────────────────

class SendCodeIn(BaseModel):
    email: EmailStr


class SendCodeOut(BaseModel):
    message: str


class RegisterIn(BaseModel):
    email: EmailStr
    code: str
    password: str

    @field_validator("code")
    @classmethod
    def validate_code_format(cls, v: str) -> str:
        normalized = v.strip()
        if not _CODE_PATTERN.match(normalized):
            raise ValueError("验证码应为 6 位数字")
        return normalized


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AuthOut(BaseModel):
    user_id: str
    email: str
    session_id: str


class MeOut(BaseModel):
    user_id: str
    email: str
    role: str
    email_verified: bool


# ── Endpoints ────────────────────────────────────────────────────────────────────

@router.post("/send-code", response_model=SendCodeOut)
async def send_code(body: SendCodeIn):
    """Send a 6-digit verification code to the given email."""
    email = _normalize_email(body.email)
    code = _generate_code()
    await _store_code(email, code)
    try:
        sent = await _send_email_code(email, code)
    except RuntimeError as exc:
        await _delete_code(email)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if sent:
        message = f"验证码已发送至 {email}，{_CODE_TTL_MINUTES} 分钟内有效"
    else:
        message = (
            f"验证码已生成（开发模式未配置邮件服务，请查看后端日志），"
            f"{_CODE_TTL_MINUTES} 分钟内有效"
        )
    return SendCodeOut(message=message)


@router.post("/register", response_model=AuthOut)
async def register(
    body: RegisterIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user with email + verification code + password."""
    email = _normalize_email(body.email)
    await _verify_code(email, body.code)
    await _delete_code(email)

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录")

    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="密码至少 8 位")

    user = User(
        id=str(uuid4()),
        email=email,
        password_hash=_hash_password(body.password),
        email_verified=True,
        role="user",
    )
    db.add(user)
    await db.flush()

    expires_at_session = datetime.now(UTC) + timedelta(days=_SESSION_DAYS)
    auth_session = AuthSession(
        id=str(uuid4()),
        user_id=user.id,
        expires_at=expires_at_session,
    )
    db.add(auth_session)
    await db.commit()

    response.set_cookie(
        key="session_token",
        value=auth_session.id,
        httponly=True,
        samesite="strict",
        expires=int(expires_at_session.timestamp()),
    )
    logger.info("user_registered", user_id=user.id, email=user.email)
    return AuthOut(user_id=user.id, email=user.email, session_id=auth_session.id)


@router.post("/login", response_model=AuthOut)
async def login(
    body: LoginIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Login with email + password."""
    email = _normalize_email(body.email)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    if not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")

    expires_at = datetime.now(UTC) + timedelta(days=_SESSION_DAYS)
    auth_session = AuthSession(
        id=str(uuid4()),
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(auth_session)
    await db.commit()

    response.set_cookie(
        key="session_token",
        value=auth_session.id,
        httponly=True,
        samesite="strict",
        expires=int(expires_at.timestamp()),
    )
    logger.info("user_logged_in", user_id=user.id, email=user.email)
    return AuthOut(user_id=user.id, email=user.email, session_id=auth_session.id)


@router.post("/logout")
async def logout(response: Response):
    """Clear session cookie."""
    response.delete_cookie("session_token")
    return {"message": "已退出登录"}


@router.get("/me", response_model=MeOut)
async def me(current_user: User | None = Depends(_get_current_user)):
    """Return current user info. 401 if not logged in."""
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录")
    return MeOut(
        user_id=current_user.id,
        email=current_user.email or "",
        role=current_user.role,
        email_verified=current_user.email_verified,
    )
