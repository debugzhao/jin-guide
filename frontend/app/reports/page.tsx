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
  low: { label: '低风险', color: 'text-green-600 bg-green-50' },
  medium: { label: '中风险', color: 'text-yellow-600 bg-yellow-50' },
  high: { label: '高风险', color: 'text-red-600 bg-red-50' },
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
      .then(setReports)
      .catch((e: Error) => setError(e.message || '加载报告列表失败'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchReports() }, [])

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      <TopNav
        title="我的报告"
        showBack
        onBack={() => router.push('/')}
        rightSlot={
          <button
            onClick={() => router.push('/profile')}
            className="flex items-center gap-1 text-xs text-blue-600 font-medium px-2 py-1 rounded-btn hover:bg-blue-50"
          >
            <PlusCircle className="w-3.5 h-3.5" />
            新建
          </button>
        }
      />

      <main className="max-w-screen-md mx-auto px-4 py-5">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
            <p className="text-sm text-gray-400">加载中...</p>
          </div>
        )}

        {error && !loading && (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <AlertCircle className="w-8 h-8 text-red-400" />
            <p className="text-sm text-gray-600">{error}</p>
            <button onClick={fetchReports} className="text-sm text-blue-600 underline">重试</button>
          </div>
        )}

        {!loading && !error && reports.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-4">
            <div className="w-16 h-16 bg-blue-50 rounded-2xl flex items-center justify-center">
              <FileText className="w-8 h-8 text-blue-400" />
            </div>
            <p className="text-sm text-gray-500">暂无志愿报告</p>
            <button
              onClick={() => router.push('/profile')}
              className="flex items-center gap-1.5 bg-blue-600 text-white text-sm font-medium px-4 py-2 rounded-xl"
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
                    'w-full bg-white rounded-xl border border-gray-200 p-4 shadow-sm',
                    'flex items-center gap-3 text-left',
                    isCompleted ? 'hover:border-blue-200 hover:shadow-md transition-shadow cursor-pointer' : 'opacity-70',
                  ].join(' ')}
                >
                  <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center shrink-0">
                    <FileText className="w-5 h-5 text-blue-600" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-gray-900 truncate">
                        志愿方案 · {r.created_at.slice(0, 10)}
                      </span>
                      {risk && (
                        <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${risk.color}`}>
                          {risk.label}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
                      <span className={isCompleted ? 'text-green-600' : 'text-gray-400'}>
                        {statusLabel}
                      </span>
                      {r.dataset_version && <span>{r.dataset_version}</span>}
                      {r.risk_score !== undefined && r.risk_score !== null && (
                        <span>风险分 {Math.round(r.risk_score)}</span>
                      )}
                    </div>
                  </div>

                  {isCompleted && <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />}
                </button>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
