from fastapi import APIRouter

from app.api.v1 import (
    admin,
    agent,
    auth,
    chat,
    data,
    notifications,
    profile,
    reports,
    risk,
    sources,
    volunteer,
)

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(profile.router, prefix="/profile", tags=["profile"])
router.include_router(agent.router, prefix="/agent", tags=["agent"])
router.include_router(reports.router, prefix="/reports", tags=["reports"])
router.include_router(chat.router, prefix="/reports", tags=["chat"])
router.include_router(data.router, prefix="/data", tags=["data"])
router.include_router(risk.router, prefix="/risk", tags=["risk"])
router.include_router(volunteer.router, prefix="/volunteer", tags=["volunteer"])
router.include_router(sources.router, prefix="/sources", tags=["sources"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
