const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    let message = `API error ${res.status}`
    try {
      const body = await res.json()
      const detail = body?.detail
      if (typeof detail === 'string') message = detail
      else if (Array.isArray(detail)) message = detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('；') || message
    } catch {
      // ignore parse errors
    }
    throw new Error(message)
  }
  // 204/无内容响应没有 body，res.json() 会因为空字符串解析失败直接抛错
  if (res.status === 204 || res.headers.get('content-length') === '0') {
    return undefined as T
  }
  return res.json()
}

export interface RiskItem {
  type: string
  level: 'error' | 'warning' | 'info'
  message: string
}

export interface FieldCheckOption {
  action: string
  label: string
}

export interface FieldCheckIssue {
  rule: string
  message: string
  options: FieldCheckOption[]
}

export interface FieldCheckResult {
  status: 'ok' | 'needs_clarification'
  next_fields: string[]
  issue: FieldCheckIssue | null
}

export interface RiskPreviewResult {
  overallRisk: 'low' | 'medium' | 'high' | 'unknown'
  riskScore: number
  scoreBand: string
  rankBand: string
  eligibleBatches: string[]
  tierCounts: { 冲: number; 稳: number; 保: number }
  riskItems: RiskItem[]
  dataAvailable: boolean
}

export const api = {
  sendCode: (email: string) =>
    apiFetch<{ message: string }>('/api/v1/auth/send-code', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  register: (data: { email: string; code: string; password: string }) =>
    apiFetch<{ user_id: string; email: string; session_id: string }>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  login: (data: { email: string; password: string }) =>
    apiFetch<{ user_id: string; email: string; session_id: string }>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  logout: () => apiFetch<{ message: string }>('/api/v1/auth/logout', { method: 'POST' }),
  me: () => apiFetch<{ user_id: string; email: string; role: string; email_verified: boolean }>('/api/v1/auth/me'),
  createProfile: async (data: unknown) => {
    const res = await apiFetch<{ id: string }>('/api/v1/profile', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    return { profileId: res.id }
  },
  getProfile: (id: string) => apiFetch<unknown>(`/api/v1/profile/${id}`),
  /**
   * 建档单字段实时校验 (docs/backend-prd-v2.md §5.6)：字段排序/跳过和矛盾检测
   * 都是确定性结果，不涉及 LLM。命中矛盾时返回 needs_clarification + 结构化选项。
   */
  checkProfileField: (params: {
    profileId?: string
    field: string
    value: unknown
    knownFields: Record<string, unknown>
  }) =>
    apiFetch<FieldCheckResult>('/api/v1/profile/field-check', {
      method: 'POST',
      body: JSON.stringify({
        profile_id: params.profileId ?? null,
        field: params.field,
        value: params.value,
        known_fields: params.knownFields,
      }),
    }),
  /**
   * 建立匿名会话（幂等）：Chat-first 首屏在未登录时用它换一个 session_token Cookie，
   * 让 /intake/chat 的历史持久化有身份可挂靠；已登录/已有会话时是无副作用的空操作。
   */
  createAnonymousSession: () =>
    apiFetch<{ anonymous_id: string; session_id: string }>('/api/v1/auth/anonymous-session', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  generateReport: async (data: { profileId: string }) => {
    const res = await apiFetch<{ run_id: string; status: string; stream_url: string }>(
      '/api/v1/reports/generate',
      { method: 'POST', body: JSON.stringify({ profile_id: data.profileId }) }
    )
    return { runId: res.run_id }
  },
  getReport: (id: string) => apiFetch<unknown>(`/api/v1/reports/${id}`),
  getReportByRun: (runId: string) => apiFetch<{ id: string }>(`/api/v1/reports/by-run/${runId}`),
  getRunStatus: (id: string) => apiFetch<{ status: string; error_msg?: string }>(`/api/v1/agent/runs/${id}`),
  getRiskPreview: async (params: {
    province: string
    score: number
    rank: number
    batch: string
    subjectType: 'physics' | 'history'
    hasPhysicalLimits: boolean
    familyBudgetPerYear?: number
  }): Promise<RiskPreviewResult> => {
    const res = await apiFetch<{
      overall_risk: string
      risk_score: number
      score_band: string
      rank_band: string
      eligible_batches: string[]
      tier_counts: Record<string, number>
      risk_items: { type: string; level: string; message: string }[]
      data_available: boolean
    }>('/api/v1/risk/preview', {
      method: 'POST',
      body: JSON.stringify({
        province: params.province,
        score: params.score,
        rank: params.rank,
        batch: params.batch,
        subject_type: params.subjectType,
        has_physical_limits: params.hasPhysicalLimits,
        family_budget_per_year: params.familyBudgetPerYear ?? null,
      }),
    })
    return {
      overallRisk: res.overall_risk as RiskPreviewResult['overallRisk'],
      riskScore: res.risk_score,
      scoreBand: res.score_band,
      rankBand: res.rank_band,
      eligibleBatches: res.eligible_batches,
      tierCounts: res.tier_counts as RiskPreviewResult['tierCounts'],
      riskItems: res.risk_items as RiskItem[],
      dataAvailable: res.data_available,
    }
  },

  checkVolunteer: async (params: {
    volunteers: {
      universityName: string
      majorName: string
      majorCategory?: string
      tier: 'high_rush' | 'rush' | 'target' | 'safe'
      rankGap?: number
      overallScore?: number
    }[]
    rejectedMajors?: string[]
  }): Promise<VolunteerCheckResult> => {
    const res = await apiFetch<{
      overall_risk: string
      risk_score: number
      risk_items: { risk_type: string; severity: string; message: string; targets: string[] }[]
      tier_distribution: Record<string, number>
      safe_count: number
      total: number
    }>('/api/v1/volunteer/check', {
      method: 'POST',
      body: JSON.stringify({
        volunteers: params.volunteers.map((v) => ({
          university_name: v.universityName,
          major_name: v.majorName,
          major_category: v.majorCategory ?? '',
          tier: v.tier,
          rank_gap: v.rankGap ?? 0,
          overall_score: v.overallScore ?? 0,
        })),
        rejected_majors: params.rejectedMajors ?? [],
      }),
    })
    return {
      overallRisk: res.overall_risk as VolunteerCheckResult['overallRisk'],
      riskScore: res.risk_score,
      riskItems: res.risk_items.map((i) => ({
        riskType: i.risk_type,
        severity: i.severity as 'high' | 'medium' | 'low',
        message: i.message,
        targets: i.targets,
      })),
      tierDistribution: res.tier_distribution,
      safeCount: res.safe_count,
      total: res.total,
    }
  },
}


// ── Chat API ──────────────────────────────────────────────────────────────────

export interface ChatHistoryMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: { source_id: string; text: string }[]
  created_at: string
}

export interface ChatHistoryResult {
  report_id: string
  messages: ChatHistoryMessage[]
  total: number
}

export const chatApi = {
  /** Load existing chat history for a report */
  getHistory: (reportId: string) =>
    apiFetch<ChatHistoryResult>(`/api/v1/reports/${reportId}/chat/history`),

  /** Clear conversation history */
  clearHistory: (reportId: string) =>
    apiFetch<void>(`/api/v1/reports/${reportId}/chat`, { method: 'DELETE' }),

  /**
   * Open a streaming SSE connection for a chat message.
   * Returns a native EventSource-compatible URL (or use fetch with ReadableStream).
   * Since EventSource doesn't support POST, we use fetch directly.
   */
  streamMessage: (
    reportId: string,
    message: string,
    callbacks: {
      onToken: (token: string) => void
      onCitation: (citation: { source_id: string; text: string }) => void
      onDone: (citations: { source_id: string; text: string }[]) => void
      onComplianceWarning: (issues: string[]) => void
      onError: (msg: string) => void
      onRateLimit: (message?: string) => void
    }
  ): (() => void) => {
    const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    let aborted = false
    const controller = new AbortController()

    const run = async () => {
      try {
        const resp = await fetch(`${BASE_URL}/api/v1/reports/${reportId}/chat`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message }),
          signal: controller.signal,
        })

        if (resp.status === 429) {
          const body = await resp.json().catch(() => ({}))
          const detail = body?.detail
          callbacks.onRateLimit(typeof detail === 'object' ? detail?.message : undefined)
          return
        }
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}))
          callbacks.onError(body?.detail?.message || body?.detail || `HTTP ${resp.status}`)
          return
        }
        if (!resp.body) return

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (!aborted) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          let currentEvent = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              const raw = line.slice(6).trim()
              try {
                const data = JSON.parse(raw)
                if (currentEvent === 'token') {
                  callbacks.onToken(data.content ?? '')
                } else if (currentEvent === 'citation') {
                  callbacks.onCitation({ source_id: data.source_id, text: data.text })
                } else if (currentEvent === 'done') {
                  callbacks.onDone(data.citations ?? [])
                } else if (currentEvent === 'compliance_warning') {
                  callbacks.onComplianceWarning(data.issues ?? [])
                } else if (currentEvent === 'error') {
                  callbacks.onError(data.message ?? '未知错误')
                }
              } catch {
                // ignore parse errors on non-JSON lines
              }
              currentEvent = ''
            }
          }
        }
      } catch (err) {
        if (!aborted) {
          callbacks.onError(err instanceof Error ? err.message : '连接中断')
        }
      }
    }

    run()
    return () => {
      aborted = true
      controller.abort()
    }
  },
}

// ── Intake Chat API（Chat-first 建档前聊天，IntakeAgent）───────────────────────

export interface IntakeChatHistoryMessage {
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface IntakeChatHistoryResult {
  messages: IntakeChatHistoryMessage[]
  total: number
}

export interface IntakeConversationListItem {
  id: string
  title: string | null
  updated_at: string
}

export interface IntakeConversationListResult {
  items: IntakeConversationListItem[]
  next_cursor: string | null
  has_more: boolean
}

export const intakeChatApi = {
  /** List the current identity's intake chat conversations (cursor-paginated, sidebar history list) */
  listConversations: (cursor?: string) =>
    apiFetch<IntakeConversationListResult>(
      `/api/v1/intake/conversations${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`
    ),

  /** Load one conversation's history. `conversationId` must belong to the current identity. */
  getHistory: (conversationId: string) =>
    apiFetch<IntakeChatHistoryResult>(
      `/api/v1/intake/chat/history?conversation_id=${encodeURIComponent(conversationId)}`
    ),

  /** Rename a conversation (sidebar history label) */
  renameConversation: (conversationId: string, title: string) =>
    apiFetch<IntakeConversationListItem>(
      `/api/v1/intake/conversations/${encodeURIComponent(conversationId)}`,
      { method: 'PATCH', body: JSON.stringify({ title }) }
    ),

  /** Soft-delete a conversation */
  deleteConversation: (conversationId: string) =>
    apiFetch<void>(`/api/v1/intake/conversations/${encodeURIComponent(conversationId)}`, {
      method: 'DELETE',
    }),

  /**
   * Open a streaming SSE connection for an intake chat message.
   * `conversationId` — pass null to let the backend lazily create a new conversation on
   * first message; `onDone` then receives the newly created id so the caller can persist it
   * for subsequent messages in the same thread.
   * `onTriggerProfileCapture` fires when IntakeAgent's `start_profile_capture` tool
   * is called — the caller should render the profile capture form inline.
   */
  streamMessage: (
    message: string,
    conversationId: string | null,
    callbacks: {
      onToken: (token: string) => void
      onTriggerProfileCapture: () => void
      onDone: (conversationId?: string) => void
      onComplianceWarning: (issues: string[]) => void
      onError: (msg: string) => void
      onRateLimit: (message?: string) => void
    }
  ): (() => void) => {
    const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    let aborted = false
    const controller = new AbortController()

    const run = async () => {
      try {
        const resp = await fetch(`${BASE_URL}/api/v1/intake/chat`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, conversation_id: conversationId ?? undefined }),
          signal: controller.signal,
        })

        if (resp.status === 429) {
          const body = await resp.json().catch(() => ({}))
          const detail = body?.detail
          callbacks.onRateLimit(typeof detail === 'object' ? detail?.message : undefined)
          return
        }
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}))
          callbacks.onError(body?.detail?.message || body?.detail || `HTTP ${resp.status}`)
          return
        }
        if (!resp.body) return

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (!aborted) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          let currentEvent = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              const raw = line.slice(6).trim()
              try {
                const data = JSON.parse(raw)
                if (currentEvent === 'token') {
                  callbacks.onToken(data.content ?? '')
                } else if (currentEvent === 'trigger_profile_capture') {
                  callbacks.onTriggerProfileCapture()
                } else if (currentEvent === 'done') {
                  callbacks.onDone(data.conversation_id)
                } else if (currentEvent === 'compliance_warning') {
                  callbacks.onComplianceWarning(data.issues ?? [])
                } else if (currentEvent === 'error') {
                  callbacks.onError(data.message ?? '未知错误')
                }
              } catch {
                // ignore parse errors on non-JSON lines
              }
              currentEvent = ''
            }
          }
        }
      } catch (err) {
        if (!aborted) {
          callbacks.onError(err instanceof Error ? err.message : '连接中断')
        }
      }
    }

    run()
    return () => {
      aborted = true
      controller.abort()
    }
  },
}

export interface VolunteerCheckResult {
  overallRisk: 'low' | 'medium' | 'high'
  riskScore: number
  riskItems: {
    riskType: string
    severity: 'high' | 'medium' | 'low'
    message: string
    targets: string[]
  }[]
  tierDistribution: Record<string, number>
  safeCount: number
  total: number
}
