'use client'

import { useEffect, useState } from 'react'
import { FileClock, RefreshCw, AlertCircle } from 'lucide-react'
import ReportCanvas from './ReportCanvas'
import { mapApiReportToViewModel, type ApiReport, type ReportViewModel } from '@/lib/reportMapping'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface LiveReportPanelProps {
  reportId: string | null
}

/**
 * 实时报告面板三态：空 / 基础版 / 偏好更新版 (F5, frontend-prd-v2.md §6.1
 * 「实时报告面板」表)。`/` 页面和 `/reports/[id]` 复用同一个组件——区别只是
 * `/` 在必填字段确认前 `reportId` 为 null（空状态），`/reports/[id]` 进入时
 * `reportId` 已确定。`reports.version` 决定"基础版"/"偏好更新版"标签
 * （docs/backend-prd-v2.md §6.4）。
 */
export default function LiveReportPanel({ reportId }: LiveReportPanelProps) {
  const [report, setReport] = useState<ReportViewModel | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!reportId) return
    setLoading(true)
    setError('')
    fetch(`${BASE_URL}/api/v1/reports/${reportId}`, { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data: ApiReport) => setReport(mapApiReportToViewModel(data)))
      .catch((e: Error) => setError(e.message || '加载报告失败'))
      .finally(() => setLoading(false))
  }, [reportId])

  if (!reportId) {
    return (
      <div className="wj-glass-card rounded-card px-6 py-12 flex flex-col items-center justify-center gap-3 text-center">
        <FileClock className="w-8 h-8 text-[#6B7280]" />
        <p className="text-sm text-[#9CA3C4]">等待基础建档信息</p>
        <p className="text-xs text-[#6B7280]">完成左侧必填信息后，这里会实时渲染报告</p>
      </div>
    )
  }

  if (loading && !report) {
    return (
      <div className="wj-glass-card rounded-card px-6 py-12 flex flex-col items-center justify-center gap-3">
        <RefreshCw className="w-6 h-6 text-[#A78BFA] animate-spin" />
        <p className="text-sm text-[#9CA3C4]">报告加载中...</p>
      </div>
    )
  }

  if (error || !report) {
    return (
      <div className="wj-glass-card rounded-card px-6 py-12 flex flex-col items-center justify-center gap-3">
        <AlertCircle className="w-6 h-6 text-[#F2A9A9]" />
        <p className="text-sm text-[#9CA3C4]">{error || '报告不存在'}</p>
      </div>
    )
  }

  const versionLabel = report.version > 1 ? '偏好更新版' : '基础版'

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[#F1F5F9]">志愿方案报告</h2>
        <span className="text-xs px-2 py-0.5 rounded-tag bg-[rgba(143,224,183,0.12)] text-[#8FE0B7] border border-[rgba(143,224,183,0.32)]">
          {versionLabel}
        </span>
      </div>
      <ReportCanvas report={report} />
    </div>
  )
}
