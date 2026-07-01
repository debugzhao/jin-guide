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
