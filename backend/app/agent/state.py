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
    profile: Optional[dict]  # StudentProfile 序列化结果
    profile_complete: bool
    profile_pending_questions: list[str]  # Profile Agent 需要追问的问题

    # ── 数据版本 ──
    dataset_version: Optional[str]
    data_warnings: list[str]  # 数据不完整时的提示

    # ── 检索结果 ──
    # 并行写入字段：必须用 Reducer，否则后写入的节点会覆盖先写入节点的结果
    evidence_list: Annotated[list[dict], operator.add]  # 追加合并，不覆盖
    retrieval_complete: bool

    # ── 规则校验结果 ──
    # 同理：Policy Rule Agent 和 Retrieval Agent 并行运行，需要 Reducer
    rule_results: Annotated[list[dict], operator.add]  # {rule_type, target, status, reason}
    hard_blocked_items: Annotated[list[str], operator.add]  # 被硬性过滤的院校/专业组 id

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
    # 同一血缘链内的版本号（首版为 1）；/refine 产出的新版本 parent_report_id 指向被 refine 的报告
    version: int
    parent_report_id: Optional[str]

    # ── 合规自检 ──
    compliance_passed: bool
    compliance_issues: list[str]
    reflection_iterations: int  # 最多 3 次；超过后直接返回尽力而为的结果

    # ── 多轮对话消息 ──
    messages: Annotated[list[BaseMessage], add_messages]

    # ── 运行元数据 ──
    started_at: str
    completed_at: Optional[str]
    error: Optional[str]
    degraded_agents: list[str]  # 记录哪些 agent 发生了降级

    # ── Debug 工具调用日志（Admin Debug Console 用，Worker 聚合 tool_call_summary） ──
    tool_call_log: Annotated[list[dict], operator.add]  # {node, tool, status, latency_ms}
