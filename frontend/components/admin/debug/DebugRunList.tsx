'use client'

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Loader2, XCircle, PauseCircle, AlertTriangle } from 'lucide-react'
import { adminApi, type AdminRunSummary } from '@/lib/adminApi'
import { useAppStore } from '@/lib/store'

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle2 className="w-3.5 h-3.5 text-green-600" />,
  running: <Loader2 className="w-3.5 h-3.5 text-blue-600 animate-spin" />,
  queued: <PauseCircle className="w-3.5 h-3.5 text-gray-400" />,
  failed: <XCircle className="w-3.5 h-3.5 text-red-600" />,
  timeout: <XCircle className="w-3.5 h-3.5 text-red-600" />,
}

const STATUS_FILTERS = ['running', 'completed', 'failed'] as const

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—'
  return `${Math.round(seconds)}s`
}

function formatCost(usd: number): string {
  return usd > 0 ? `$${usd.toFixed(2)}` : '—'
}

export default function DebugRunList() {
  const { selectedRunId, setSelectedRunId, isLiveFollowing, setIsLiveFollowing } = useAppStore()
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [onlyDegraded, setOnlyDegraded] = useState(false)
  const [onlyHumanReview, setOnlyHumanReview] = useState(false)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['admin', 'runs', statusFilter],
    queryFn: () => adminApi.listRuns({ limit: 50, status: statusFilter }),
    refetchInterval: 10000,
  })

  const runs = (data ?? []).filter((r) => {
    if (onlyDegraded && r.degraded_agents.length === 0) return false
    if (onlyHumanReview && !r.triggered_human_review) return false
    return true
  })

  // "实时跟随": auto-select the newest run whenever the list refreshes
  useEffect(() => {
    if (!isLiveFollowing || runs.length === 0) return
    if (runs[0].id !== selectedRunId) setSelectedRunId(runs[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLiveFollowing, runs.map((r) => r.id).join(',')])

  return (
    <div className="w-[240px] flex-shrink-0 border-r border-gray-200 bg-white flex flex-col h-full">
      <div className="px-3 py-2.5 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
        <span className="text-xs font-semibold text-gray-700">Run 列表</span>
        <button
          onClick={() => setIsLiveFollowing(!isLiveFollowing)}
          className={`text-[10px] px-2 py-0.5 rounded-full font-medium transition-colors ${
            isLiveFollowing ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
          }`}
        >
          实时跟随{isLiveFollowing ? '开' : '关'}
        </button>
      </div>

      <div className="px-3 py-2 border-b border-gray-100 space-y-1.5 flex-shrink-0">
        <select
          value={statusFilter ?? ''}
          onChange={(e) => setStatusFilter(e.target.value || undefined)}
          className="w-full text-[11px] border border-gray-200 rounded-md px-1.5 py-1 text-gray-600"
        >
          <option value="">全部状态</option>
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-[11px] text-gray-600">
          <input type="checkbox" checked={onlyDegraded} onChange={(e) => setOnlyDegraded(e.target.checked)} />
          仅含降级
        </label>
        <label className="flex items-center gap-1.5 text-[11px] text-gray-600">
          <input
            type="checkbox"
            checked={onlyHumanReview}
            onChange={(e) => setOnlyHumanReview(e.target.checked)}
          />
          仅触发人工复核
        </label>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading && <p className="text-[11px] text-gray-400 text-center py-6">加载中...</p>}
        {isError && (
          <div className="text-center py-6 px-3">
            <p className="text-[11px] text-red-500 mb-2">加载失败</p>
            <button onClick={() => refetch()} className="text-[11px] text-blue-600 underline">
              重试
            </button>
          </div>
        )}
        {!isLoading && !isError && runs.length === 0 && (
          <p className="text-[11px] text-gray-400 text-center py-6 px-3">
            还没有 run 记录，生成一份报告后再来看
          </p>
        )}
        {runs.map((run) => (
          <RunRow key={run.id} run={run} selected={run.id === selectedRunId} onClick={() => setSelectedRunId(run.id)} />
        ))}
      </div>
    </div>
  )
}

function RunRow({
  run,
  selected,
  onClick,
}: {
  run: AdminRunSummary
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2 border-b border-gray-50 hover:bg-gray-50 transition-colors ${
        selected ? 'bg-blue-50' : ''
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-mono text-gray-700 truncate">{run.id.slice(0, 8)}…</span>
        {STATUS_ICON[run.status] ?? <PauseCircle className="w-3.5 h-3.5 text-gray-400" />}
      </div>
      <div className="flex items-center gap-2 mt-1 text-[10px] text-gray-400">
        <span>{formatDuration(run.duration_seconds)}</span>
        <span>{formatCost(run.cost_usd)}</span>
        {run.degraded_agents.length > 0 && (
          <AlertTriangle className="w-3 h-3 text-amber-500" aria-label="含降级" />
        )}
        {run.triggered_human_review && (
          <span className="w-1.5 h-1.5 rounded-full bg-orange-400" aria-label="触发人工复核" />
        )}
      </div>
    </button>
  )
}
