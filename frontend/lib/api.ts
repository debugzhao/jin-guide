const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

export interface RiskItem {
  type: string
  level: 'error' | 'warning' | 'info'
  message: string
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
  createSession: async () => {
    const res = await apiFetch<{ session_id: string; token: string; expires_at: string }>(
      '/api/v1/auth/session',
      { method: 'POST', body: '{}' }
    )
    return { sessionId: res.session_id, token: res.token }
  },
  createProfile: async (data: unknown) => {
    const res = await apiFetch<{ id: string }>('/api/v1/profile', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    return { profileId: res.id }
  },
  getProfile: (id: string) => apiFetch<unknown>(`/api/v1/profile/${id}`),
  generateReport: async (data: { profileId: string }) => {
    const res = await apiFetch<{ run_id: string; status: string; stream_url: string }>(
      '/api/v1/reports/generate',
      { method: 'POST', body: JSON.stringify({ profile_id: data.profileId }) }
    )
    return { runId: res.run_id }
  },
  getReport: (id: string) => apiFetch<unknown>(`/api/v1/reports/${id}`),
  getRunStatus: (id: string) => apiFetch<unknown>(`/api/v1/agent/runs/${id}`),
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

// ── Review API ──────────────────────────────────────────────────────────────

export interface ReviewChecklistItem {
  id: string
  item: string
  required: boolean
}

export interface ReviewChecklistJson {
  summary: string
  trigger_reasons: string[]
  risk_items: { risk_type: string; severity: string; targets: string[]; message: string }[]
  compliance_issues: string[]
  data_warnings: string[]
  reviewer_checklist: ReviewChecklistItem[]
}

export interface ReviewOut {
  id: string
  report_id: string | null
  run_id: string | null
  reviewer_id: string | null
  status: string
  checklist_json: ReviewChecklistJson | null
  conclusion: string | null
  reviewer_notes: string | null
  created_at: string
  completed_at: string | null
  timeout_at: string | null
}

export interface ReviewListItem {
  id: string
  report_id: string | null
  run_id: string | null
  status: string
  conclusion: string | null
  created_at: string
  timeout_at: string | null
}

export const reviewApi = {
  // 复核员工作台：按状态列出复核任务
  list: (status?: string) =>
    apiFetch<ReviewListItem[]>(
      `/api/v1/reviews${status ? `?status=${status}` : '?limit=50'}`
    ),

  // 查单条复核（含 checklist_json）
  get: (id: string) => apiFetch<ReviewOut>(`/api/v1/reviews/${id}`),

  // 按 run_id 查所属复核（用户侧进入复核页）
  getByRunId: (runId: string) =>
    apiFetch<ReviewListItem[]>(`/api/v1/reviews?run_id=${runId}&limit=1`),

  // 按 report_id 查所属复核（报告页 HITL 入口 / 用户侧复核页）
  // 后端按 created_at asc 排序，取最后一条即最新记录
  getByReportId: async (reportId: string): Promise<ReviewListItem | null> => {
    const list = await apiFetch<ReviewListItem[]>(
      `/api/v1/reviews?report_id=${reportId}&limit=20`
    )
    return list.length > 0 ? list[list.length - 1] : null
  },

  // 用户主动申请人工复核（幂等：已有未关闭的复核则直接返回该条）
  create: (reportId: string, reason?: string) =>
    apiFetch<ReviewOut>('/api/v1/reviews', {
      method: 'POST',
      body: JSON.stringify({ report_id: reportId, reason: reason ?? null }),
    }),

  // 复核员领取任务（→ status: in_review）
  claim: (id: string, reviewerId: string) =>
    apiFetch<ReviewOut>(`/api/v1/reviews/${id}/claim`, {
      method: 'PATCH',
      body: JSON.stringify({ reviewer_id: reviewerId }),
    }),

  // 提交复核结论
  submitConclusion: (
    id: string,
    payload: {
      conclusion: 'approved' | 'rejected' | 'need_more_info'
      reviewer_id?: string
      reviewer_notes?: string
      override_risk_level?: string
      checklist_results?: { id: string; verdict: 'pass' | 'flag' }[]
    }
  ) =>
    apiFetch<ReviewOut>(`/api/v1/reviews/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
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
