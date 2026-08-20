# 在这里统一导入所有模型，让 Alembic 能通过 Base.metadata 发现它们
from app.models.base import Base
from app.models.user import User, AuthSession
from app.models.profile import StudentProfile, Preference
from app.models.agent_run import AgentRun
from app.models.report import Report, VolunteerCheck
from app.models.document import Document, Chunk
from app.models.conversation import (
    ReportConversation,
    IntakeConversation,
    ConversationMessage,
    ConversationSummary,
)
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
from app.models.prompt_invocation import PromptInvocation

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
    "ReportConversation",
    "IntakeConversation",
    "ConversationMessage",
    "ConversationSummary",
    "University",
    "AdmissionScore",
    "RankSegment",
    "SubjectRequirement",
    "ProvinceThreshold",
    "AdmissionPlan",
    "RuleRequirement",
    "Notification",
    "PromptInvocation",
]
