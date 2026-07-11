import type { Candidate, RiskItem } from '@/types'

/**
 * `GET /api/v1/reports/{id}` 原始响应形状 + 前端展示所需的 view model 映射。
 * 抽取自旧版 `app/reports/[id]/page.tsx`，供 ReportCanvas 在 `/` 实时报告面板
 * 和 `/reports/[id]` 两处复用，避免各自维护一份映射逻辑。
 */

export interface ApiPlanCandidate {
  id?: string
  university_id?: string
  university_name?: string
  university_city?: string
  city?: string
  tier?: string
  major_name?: string
  major_group?: string
  admission_safety_score?: number
  matching_confidence_score?: number
  overall_score?: number
  tuition_per_year?: number
  subject_requirements?: string[] | string
  historical_ranks?: { year: number; min_rank: number }[]
  recommendation_reasons?: string[]
  evidence_ids?: string[]
}

export interface ApiPlan {
  type: string
  candidates: ApiPlanCandidate[]
}

export interface ApiRunSummary {
  node_timings?: Record<string, number>
  degraded_agents?: string[]
  reflection_iterations?: number
}

export interface ApiReport {
  id: string
  status: string
  risk_level?: string
  version?: number
  parent_report_id?: string | null
  run_summary_json?: ApiRunSummary | null
  created_at: string
  plan_json?: {
    condition_commentary?: string | null
    profile_summary?: { province?: string; score?: number; rank?: number; subjects?: string[] }
    risk_level?: string
    risk_items?: { level: string; description: string }[]
    plans?: ApiPlan[]
  }
}

export function mapTier(tier: string): 'rush' | 'target' | 'safe' {
  if (tier === 'high_rush' || tier === 'rush') return 'rush'
  if (tier === 'safe') return 'safe'
  return 'target'
}

export function mapCandidate(c: ApiPlanCandidate, idx: number): Candidate {
  const subjectReqs = Array.isArray(c.subject_requirements)
    ? (c.subject_requirements as string[]).join('、') || '不限'
    : (c.subject_requirements as string) || '不限'

  return {
    id: c.id || c.university_id || `cand-${idx}`,
    schoolName: c.university_name || '',
    city: c.university_city || c.city || '',
    tier: mapTier(c.tier || 'target'),
    majorName: c.major_name || '',
    majorGroupCode: c.major_group || '',
    safetyScore: Math.round(c.admission_safety_score ?? 50),
    overallScore: Math.round(c.overall_score ?? 0),
    tuitionPerYear: c.tuition_per_year ?? 0,
    subjectRequirements: subjectReqs,
    reasons: c.recommendation_reasons || [],
    evidenceIds: c.evidence_ids,
  }
}

export interface ReportViewModel {
  id: string
  status: string
  createdAt: string
  version: number
  conditionCommentary: string | null
  runSummary: ApiRunSummary | null
  province?: string
  score?: number
  rank?: number
  subjects?: string[]
  overallRisk: RiskItem['level']
  riskItems: RiskItem[]
  plansMap: Record<string, Candidate[]>
}

export function mapApiReportToViewModel(report: ApiReport): ReportViewModel {
  const planJson = report.plan_json || {}
  const summary = planJson.profile_summary || {}
  const riskItems: RiskItem[] = (planJson.risk_items || []).map((r) => ({
    level: r.level as RiskItem['level'],
    description: r.description,
  }))
  const overallRisk = (planJson.risk_level || report.risk_level || 'low') as RiskItem['level']

  const plansMap: Record<string, Candidate[]> = {}
  for (const plan of planJson.plans || []) {
    plansMap[plan.type] = (plan.candidates || []).map(mapCandidate)
  }

  return {
    id: report.id,
    status: report.status,
    createdAt: report.created_at,
    version: report.version ?? 1,
    conditionCommentary: planJson.condition_commentary || null,
    runSummary: report.run_summary_json || null,
    province: summary.province,
    score: summary.score,
    rank: summary.rank,
    subjects: summary.subjects,
    overallRisk,
    riskItems,
    plansMap,
  }
}
