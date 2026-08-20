export type RiskLevel = 'high' | 'medium' | 'low' | 'info'

export type PlanType = 'conservative' | 'balanced' | 'aggressive'

export type BadgeVariant =
  | 'rush'
  | 'target'
  | 'safe'
  | 'high_rush'
  | 'high'
  | 'medium'
  | 'low'
  | 'info'

export interface Candidate {
  id: string
  schoolName: string
  city: string
  tier: 'rush' | 'target' | 'safe'
  majorName: string
  majorGroupCode: string
  safetyScore: number
  overallScore: number
  tuitionPerYear: number
  subjectRequirements: string
  reasons: string[]
  dataSourceUrl?: string
  evidenceIds?: string[]   // 源文档 ID 列表，供 EvidenceDrawer 展示引用来源
}

export interface RiskItem {
  level: RiskLevel
  description: string
}

export interface Report {
  id: string
  createdAt: string
  province: string
  score: number
  rank: number
  subjects: string[]
  overallRisk: RiskLevel
  riskItems: RiskItem[]
  plans: {
    conservative: Candidate[]
    balanced: Candidate[]
    aggressive: Candidate[]
  }
}

export interface ProfileData {
  province: string
  batch: string
  score: number
  rank?: number
  subjects: string[]
  gender: string
  hasPhysicalLimits: boolean
  budgetRange?: string
  acceptsOutOfProvince?: boolean
  riskStyle?: PlanType
  preferredCities?: string[]
  excludedCities?: string[]
  interestedMajors?: string[]
  excludedMajors?: string[]
  planToGraduateSchool?: boolean
  careerKeywords?: string
}

export type StepStatus = 'waiting' | 'running' | 'completed' | 'failed'

export interface AgentStep {
  id: string
  label: string
  status: StepStatus
}

// ── 聊天面板 ──────────────────────────────────────────────────────────────

export interface ChatCitation {
  source_id: string
  text: string
}

export type ChatMessageRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: ChatMessageRole
  content: string
  citations: ChatCitation[]
  created_at: string
  /** 可选，模型推理过程——由后端开关控制是否下发，只在当前浏览器会话内展示，不做持久化。 */
  thinking?: string
  /** 助手消息仍在流式接收 token 时为 true */
  streaming?: boolean
}

export interface ChatState {
  isChatPanelOpen: boolean
  /** 该聊天会话所属的 report_id */
  activeReportId: string | null
  messages: ChatMessage[]
  /** 当前流式消息累积到的 token 内容 */
  streamingContent: string
  isStreaming: boolean
  dailyLimitReached: boolean
}

// ── Admin Debug Console ──────────────────────────────────────────────────────

/** 节点的可视化状态——与 LangGraph run 发出的调试事件负载一一对应。 */
export type NodeStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'degraded'
  | 'failed'
  | 'interrupted'
  | 'skipped'

export interface DebugNodeState {
  status: NodeStatus
  latencyMs?: number
  /** Reflection 重试计数，例如 1/3 */
  iteration?: number
}

export interface DebugEvent {
  id: string
  /** 事件类型，不含 "debug:" 前缀，例如 node_started、tool_called */
  type: string
  ts: number
  node?: string
  raw: Record<string, unknown>
}

export interface DebugRunFilter {
  status?: 'running' | 'completed' | 'failed' | 'interrupted'
  onlyDegraded?: boolean
  onlyHumanReview?: boolean
}
