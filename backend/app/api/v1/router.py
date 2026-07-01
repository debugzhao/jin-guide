from fastapi import APIRouter

from app.api.v1 import auth, profile, agent, reports, data, risk

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(profile.router, prefix="/profile", tags=["profile"])
router.include_router(agent.router, prefix="/agent", tags=["agent"])
router.include_router(reports.router, prefix="/reports", tags=["reports"])
router.include_router(data.router, prefix="/data", tags=["data"])
router.include_router(risk.router, prefix="/risk", tags=["risk"])
