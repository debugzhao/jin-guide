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
import string
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from app.config import settings
from app.database import get_db
from app.models.user import Session, User

logger = structlog.get_logger()
router = APIRouter()

# In-memory code store: {email: (code, expires_at)}
# For production replace with Redis (TTL-backed).
_pending_codes: dict[str, tuple[str, datetime]] = {}

_CODE_TTL_MINUTES = 10
_SESSION_DAYS = 30


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """SHA-256 HMAC with SECRET_KEY as salt. For production use bcrypt/argon2."""
    return hashlib.sha256(
        settings.secret_key.encode() + password.encode()
    ).hexdigest()


def _verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(_hash_password(password), password_hash)  # constant-time compare


def _generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


async def _send_email_code(email: str, code: str) -> None:
    """
    Send verification code email.
    MVP: logs the code (no SMTP configured yet).
    Production: replace with SMTP / SendGrid / Resend.
    """
    logger.info("email_verification_code", email=email, code=code)
    # TODO: integrate real email provider


async def _get_current_user(
    session_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not session_token:
        return None
    result = await db.execute(
        select(Session).where(
            Session.id == session_token,
            Session.expires_at > datetime.now(UTC),
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
    """
    Send a 6-digit verification code to the given email.
    Rate limiting and SMTP integration should be added before production.
    """
    code = _generate_code()
    _pending_codes[body.email] = (code, datetime.now(UTC) + timedelta(minutes=_CODE_TTL_MINUTES))
    await _send_email_code(body.email, code)
    return SendCodeOut(message=f"验证码已发送至 {body.email}，{_CODE_TTL_MINUTES} 分钟内有效")


@router.post("/register", response_model=AuthOut)
async def register(
    body: RegisterIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user with email + verification code + password."""
    # Validate code
    entry = _pending_codes.get(body.email)
    if not entry:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    code, expires_at = entry
    if datetime.now(UTC) > expires_at:
        _pending_codes.pop(body.email, None)
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if not hmac.compare_digest(code, body.code):
        raise HTTPException(status_code=400, detail="验证码不正确")
    _pending_codes.pop(body.email, None)

    # Check duplicate email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录")

    # Password strength: at least 8 chars
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="密码至少 8 位")

    user = User(
        id=str(uuid4()),
        email=body.email,
        password_hash=_hash_password(body.password),
        email_verified=True,
        role="user",
    )
    db.add(user)

    expires_at_session = datetime.now(UTC) + timedelta(days=_SESSION_DAYS)
    session = Session(
        id=str(uuid4()),
        user_id=user.id,
        expires_at=expires_at_session,
    )
    db.add(session)
    await db.commit()

    response.set_cookie(
        key="session_token",
        value=session.id,
        httponly=True,
        samesite="strict",
        expires=int(expires_at_session.timestamp()),
    )
    logger.info("user_registered", user_id=user.id, email=user.email)
    return AuthOut(user_id=user.id, email=user.email, session_id=session.id)


@router.post("/login", response_model=AuthOut)
async def login(
    body: LoginIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Login with email + password."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    if not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")

    expires_at = datetime.now(UTC) + timedelta(days=_SESSION_DAYS)
    session = Session(
        id=str(uuid4()),
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()

    response.set_cookie(
        key="session_token",
        value=session.id,
        httponly=True,
        samesite="strict",
        expires=int(expires_at.timestamp()),
    )
    logger.info("user_logged_in", user_id=user.id, email=user.email)
    return AuthOut(user_id=user.id, email=user.email, session_id=session.id)


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
