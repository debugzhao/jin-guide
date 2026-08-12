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
  evidenceIds?: string[]   // source document IDs for EvidenceDrawer
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

// ── Chat Panel ──────────────────────────────────────────────────────────────

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
  /** True while the assistant message is still streaming tokens */
  streaming?: boolean
}

export interface ChatState {
  isChatPanelOpen: boolean
  /** The report_id this chat session belongs to */
  activeReportId: string | null
  messages: ChatMessage[]
  /** Tokens accumulating for the current streaming message */
  streamingContent: string
  isStreaming: boolean
  dailyLimitReached: boolean
}

// ── Admin Debug Console ──────────────────────────────────────────────────────

/** Node visual states — mirrors debug event payloads from the LangGraph run. */
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
  /** Reflection retry counter, e.g. 1/3 */
  iteration?: number
}

export interface DebugEvent {
  id: string
  /** Event type without the "debug:" prefix, e.g. node_started, tool_called */
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
