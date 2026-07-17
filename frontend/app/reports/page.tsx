'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { FileText, ChevronRight, AlertCircle, RefreshCw, PlusCircle } from 'lucide-react'
import TopNav from '@/components/layout/TopNav'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface ReportListItem {
  id: string
  profile_id?: string
  status: string
  risk_level?: string
  risk_score?: number
  dataset_version?: string
  created_at: string
}

const RISK_LABEL: Record<string, { label: string; color: string }> = {
  low: { label: '低风险', color: 'text-[#16A34A] bg-[#F0FDF4]' },
  medium: { label: '中风险', color: 'text-[#D97706] bg-[#FFFBEB]' },
  high: { label: '高风险', color: 'text-[#DC2626] bg-[#FEF2F2]' },
}

const STATUS_LABEL: Record<string, string> = {
  completed: '已完成',
  generating: '生成中',
  queued: '排队中',
  failed: '失败',
}

export default function ReportsPage() {
  const router = useRouter()
  const [reports, setReports] = useState<ReportListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchReports = () => {
    setLoading(true)
    setError('')
    fetch(`${BASE_URL}/api/v1/reports?limit=20`, { credentials: 'include' })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((data: { items: ReportListItem[] }) => setReports(data.items))
      .catch((e: Error) => setError(e.message || '加载报告列表失败'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchReports() }, [])

  return (
    <div className="min-h-screen">
      <TopNav
        title="我的报告"
        showBack
        onBack={() => router.push('/')}
        rightSlot={
          <button
            onClick={() => router.push('/')}
            className="flex items-center gap-1 text-xs text-[#1E40AF] font-medium px-2 py-1 rounded-btn hover:bg-[#F1F5F9]"
          >
            <PlusCircle className="w-3.5 h-3.5" />
            新建
          </button>
        }
      />

      <main className="max-w-screen-md mx-auto px-4 py-5">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <RefreshCw className="w-6 h-6 text-[#1E40AF] animate-spin" />
            <p className="text-sm text-[#94A3B8]">加载中...</p>
          </div>
        )}

        {error && !loading && (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <AlertCircle className="w-8 h-8 text-[#DC2626]" />
            <p className="text-sm text-[#64748B]">{error}</p>
            <button onClick={fetchReports} className="text-sm text-[#1E40AF] underline">重试</button>
          </div>
        )}

        {!loading && !error && reports.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-4">
            <div className="w-16 h-16 bg-[#EFF6FF] rounded-bubble flex items-center justify-center">
              <FileText className="w-8 h-8 text-[#1E40AF]" />
            </div>
            <p className="text-sm text-[#64748B]">暂无志愿报告</p>
            <button
              onClick={() => router.push('/')}
              className="flex items-center gap-1.5 bg-[#1E40AF] hover:bg-[#1E3A8A] text-white text-sm font-medium px-4 py-2 rounded-card transition-colors"
            >
              <PlusCircle className="w-4 h-4" />
              建档生成报告
            </button>
          </div>
        )}

        {!loading && !error && reports.length > 0 && (
          <div className="space-y-3">
            {reports.map((r) => {
              const risk = RISK_LABEL[r.risk_level || '']
              const statusLabel = STATUS_LABEL[r.status] || r.status
              const isCompleted = r.status === 'completed'

              return (
                <button
                  key={r.id}
                  onClick={() => isCompleted && router.push(`/reports/${r.id}`)}
                  disabled={!isCompleted}
                  className={[
                    'w-full wj-glass-card rounded-card p-4',
                    'flex items-center gap-3 text-left',
                    isCompleted ? 'hover:border-[#1E40AF]/30 transition-colors cursor-pointer' : 'opacity-70',
                  ].join(' ')}
                >
                  <div className="w-10 h-10 bg-[#EFF6FF] rounded-card flex items-center justify-center shrink-0">
                    <FileText className="w-5 h-5 text-[#1E40AF]" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-[#0F172A] truncate">
                        志愿方案 · {r.created_at.slice(0, 10)}
                      </span>
                      {risk && (
                        <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${risk.color}`}>
                          {risk.label}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-[#94A3B8]">
                      <span className={isCompleted ? 'text-[#16A34A]' : 'text-[#94A3B8]'}>
                        {statusLabel}
                      </span>
                      {r.dataset_version && <span>{r.dataset_version}</span>}
                      {r.risk_score !== undefined && r.risk_score !== null && (
                        <span>风险分 {Math.round(r.risk_score)}</span>
                      )}
                    </div>
                  </div>

                  {isCompleted && <ChevronRight className="w-4 h-4 text-[#94A3B8] shrink-0" />}
                </button>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
