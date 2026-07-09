# Import all models here so Alembic can discover them via Base.metadata
from app.models.base import Base
from app.models.user import User, AuthSession
from app.models.profile import StudentProfile, Preference
from app.models.agent_run import AgentRun
from app.models.report import Report, VolunteerCheck
from app.models.document import Document, Chunk
from app.models.admission import (
    University,
    AdmissionScore,
    RankSegment,
    SubjectRequirement,
    ProvinceThreshold,
    AdmissionPlan,
    RuleRequirement,
)
from app.models.notification import Notification

__all__ = [
    "Base",
    "User",
    "AuthSession",
    "StudentProfile",
    "Preference",
    "AgentRun",
    "Report",
    "VolunteerCheck",
    "Document",
    "Chunk",
    "University",
    "AdmissionScore",
    "RankSegment",
    "SubjectRequirement",
    "ProvinceThreshold",
    "AdmissionPlan",
    "RuleRequirement",
    "Notification",
]
