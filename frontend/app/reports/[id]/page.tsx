'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Share2, AlertCircle, RefreshCw, MessageCircle } from 'lucide-react'
import TopNav from '@/components/layout/TopNav'
import RiskOverview from '@/components/report/RiskOverview'
import PlanTabs from '@/components/report/PlanTabs'
import CandidateCard from '@/components/report/CandidateCard'
import ChatPanel from '@/components/chat/ChatPanel'
import { useAppStore } from '@/lib/store'
import type { Candidate, PlanType, RiskItem } from '@/types'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface ApiPlanCandidate {
  id?: string
  university_id?: string
  university_name?: string
  university_city?: string
  city?: string
  tier?: string
  major_name?: string
  major_group?: string
  admission_safety_score?: number
  overall_score?: number
  tuition_per_year?: number
  subject_requirements?: string[] | string
  recommendation_reasons?: string[]
  evidence_ids?: string[]
}

interface ApiPlan {
  type: string
  candidates: ApiPlanCandidate[]
}

interface ApiReport {
  id: string
  status: string
  risk_level?: string
  created_at: string
  plan_json?: {
    profile_summary?: { province?: string; score?: number; rank?: number; subjects?: string[] }
    risk_level?: string
    risk_items?: { level: string; description: string }[]
    plans?: ApiPlan[]
  }
}

function mapTier(tier: string): 'rush' | 'target' | 'safe' {
  if (tier === 'high_rush' || tier === 'rush') return 'rush'
  if (tier === 'safe') return 'safe'
  return 'target'
}

function mapCandidate(c: ApiPlanCandidate, idx: number): Candidate {
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

const PLAN_DESC: Record<string, string> = {
  conservative: '以稳为主，优先确保录取成功率，适合求稳的考生',
  balanced: '冲稳保均衡分配，综合性价比最高，AI 推荐方案',
  aggressive: '优先冲击高层次院校，适合心态好、不怕复读的考生',
}

export default function ReportDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const { currentTab, setCurrentTab, openChatPanel, isChatPanelOpen } = useAppStore()

  const [report, setReport] = useState<ApiReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    fetch(`${BASE_URL}/api/v1/reports/${id}`, { credentials: 'include' })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setReport)
      .catch((e: Error) => setError(e.message || '加载报告失败'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center gap-3">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <p className="text-sm text-gray-400">加载报告中...</p>
      </div>
    )
  }

  if (error || !report) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center gap-3">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-sm text-gray-600">{error || '报告不存在'}</p>
        <button onClick={() => router.back()} className="text-sm text-blue-600 underline">返回</button>
      </div>
    )
  }

  if (report.status !== 'completed') {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center gap-3">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <p className="text-sm text-gray-600">报告生成中，请稍候...</p>
        <button onClick={() => window.location.reload()} className="mt-2 text-sm text-blue-600 underline">刷新</button>
      </div>
    )
  }

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

  const activePlan = (currentTab as PlanType) in plansMap ? (currentTab as PlanType) : 'balanced'
  const candidates = plansMap[activePlan] ?? []

  const handleShare = async () => {
    try { await navigator.share({ title: '我的高考志愿方案', url: window.location.href }) } catch {}
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      <TopNav
        title="志愿方案"
        showBack
        onBack={() => router.push('/reports')}
        rightSlot={
          <button onClick={handleShare} className="p-2 rounded-btn text-[#64748B] hover:text-[#0F172A] hover:bg-[#F1F5F9]">
            <Share2 className="w-4.5 h-4.5" />
          </button>
        }
      />

      <main className="max-w-screen-md mx-auto px-4 py-5 space-y-4">
        <div className="flex items-center gap-3 text-xs text-[#64748B] flex-wrap">
          {summary.province && <span>{summary.province} · {summary.score} 分</span>}
          {summary.rank && <span>全省第 {summary.rank.toLocaleString('zh-CN')} 名</span>}
          {summary.subjects && <span>{summary.subjects.join('/')} 选科</span>}
          <span className="ml-auto">{report.created_at.slice(0, 10)}</span>
        </div>

        <RiskOverview overallRisk={overallRisk} riskItems={riskItems} />
        <PlanTabs currentTab={activePlan} onChange={setCurrentTab} />

        <div className="text-xs text-[#64748B] px-1">{PLAN_DESC[activePlan] || ''}</div>

        {candidates.length > 0 ? (
          <div className="space-y-3">
            {candidates.map((c, i) => <CandidateCard key={c.id} candidate={c} rank={i + 1} />)}
          </div>
        ) : (
          <div className="py-10 text-center text-sm text-gray-400">暂无候选院校数据</div>
        )}

        <div className="pb-6" />
      </main>

      {/* Floating "问一问" button — only shown on completed reports */}
      {!isChatPanelOpen && (
        <button
          onClick={() => openChatPanel(id)}
          className="fixed bottom-6 right-5 z-30 flex items-center gap-2 px-4 py-2.5
            bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-full
            shadow-lg hover:shadow-xl transition-all active:scale-95"
          aria-label="打开 AI 助手"
        >
          <MessageCircle className="w-4 h-4" />
          <span>问一问</span>
        </button>
      )}

      {/* Chat Panel (Drawer / Sheet) */}
      <ChatPanel reportId={id} />
    </div>
  )
}
