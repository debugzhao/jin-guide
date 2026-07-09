import operator
from typing import Annotated, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class VolunteerPlanState(TypedDict):
    # ── 基础信息 ──
    run_id: str
    thread_id: str
    user_id: str
    anonymous_id: str
    profile_id: str
    task_type: Literal["generate_report", "check_volunteer"]

    # ── 档案 ──
    profile: Optional[dict]  # StudentProfile serialized
    profile_complete: bool
    profile_pending_questions: list[str]  # Questions Profile Agent needs to ask

    # ── 数据版本 ──
    dataset_version: Optional[str]
    data_warnings: list[str]  # Incomplete data hints

    # ── 检索结果 ──
    # Parallel write fields: must use Reducer to prevent later node from overwriting earlier
    evidence_list: Annotated[list[dict], operator.add]  # append-merge, no overwrite
    retrieval_complete: bool

    # ── 规则校验结果 ──
    # Same: Policy Rule Agent and Retrieval Agent run in parallel, need Reducer
    rule_results: Annotated[list[dict], operator.add]  # {rule_type, target, status, reason}
    hard_blocked_items: Annotated[list[str], operator.add]  # hard-filtered school/major group ids

    # ── 候选集 ──
    candidates: list[dict]
    scored_candidates: list[dict]
    tier_summary: dict  # {rush: N, target: N, safe: N}

    # ── 风险检查 ──
    risk_items: list[dict]  # {risk_type, severity, message, targets}
    overall_risk_level: Literal["low", "medium", "high"]

    # ── 报告 ──
    report_draft: Optional[dict]
    report_id: Optional[str]

    # ── 合规自检 ──
    compliance_passed: bool
    compliance_issues: list[str]
    reflection_iterations: int  # Max 3; after that best-effort result is returned

    # ── 多轮对话消息 ──
    messages: Annotated[list[BaseMessage], add_messages]

    # ── 运行元数据 ──
    started_at: str
    completed_at: Optional[str]
    error: Optional[str]
    degraded_agents: list[str]  # Track which agents degraded

    # ── Debug 工具调用日志（Admin Debug Console 用，Worker 聚合 tool_call_summary） ──
    tool_call_log: Annotated[list[dict], operator.add]  # {node, tool, status, latency_ms}
