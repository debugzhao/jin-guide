from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import Session

router = APIRouter()


class SessionResponse(BaseModel):
    session_id: str
    token: str
    expires_at: str


@router.post("/session", response_model=SessionResponse)
async def create_session(
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Create an anonymous session. Implements the anonymous-first auth strategy from PRD 7.4."""
    anonymous_id = str(uuid4())
    session_id = str(uuid4())
    expires_at = datetime.now(UTC) + timedelta(days=30)

    session = Session(
        id=session_id,
        user_id=None,
        anonymous_id=anonymous_id,
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # Set HttpOnly cookie for SSE auth (see PRD 5.3)
    response.set_cookie(
        key="session_token",
        value=session_id,
        httponly=True,
        samesite="strict",
        expires=int(expires_at.timestamp()),
    )

    return SessionResponse(
        session_id=session_id,
        token=session_id,  # M1: token == session_id; M2 replace with signed JWT
        expires_at=expires_at.isoformat(),
    )
