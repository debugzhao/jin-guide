'use client'

import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { adminApi } from '@/lib/adminApi'

const ERROR_RATE_ALERT_THRESHOLD = 10 // %
const AVG_DURATION_ALERT_THRESHOLD = 60 // seconds

export default function DebugMetricsBar() {
  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'metrics-summary'],
    queryFn: adminApi.getMetricsSummary,
    refetchInterval: 30000,
  })

  const errorRateHigh = (data?.error_rate_pct ?? 0) > ERROR_RATE_ALERT_THRESHOLD
  const durationHigh = (data?.avg_duration_seconds ?? 0) > AVG_DURATION_ALERT_THRESHOLD

  return (
    <div
      className={`flex items-center justify-between px-4 py-2 border-b text-xs ${
        errorRateHigh ? 'bg-red-50 border-red-200' : 'bg-white border-gray-100'
      }`}
    >
      <div className="flex items-center gap-5 text-gray-500">
        <span>
          错误率{' '}
          <strong className={errorRateHigh ? 'text-red-600' : 'text-gray-900'}>
            {isLoading ? '—' : `${data?.error_rate_pct ?? 0}%`}
          </strong>
        </span>
        <span>
          平均耗时{' '}
          {/* PRD 要求 P95，后端 metrics/summary 目前只有均值，先展示均值，避免前端编造分位数 */}
          <strong className={durationHigh ? 'text-red-600' : 'text-gray-900'}>
            {isLoading || data?.avg_duration_seconds == null ? '—' : `${data.avg_duration_seconds}s`}
          </strong>
        </span>
        <span>
          今日费用 <strong className="text-gray-900">${(data?.total_cost_usd_24h ?? 0).toFixed(2)}</strong>
        </span>
        <span>
          今日运行 <strong className="text-gray-900">{data?.total_runs_24h ?? '—'}</strong>
        </span>
        <span>
          运行中 <strong className="text-gray-900">{data?.active_runs ?? '—'}</strong>
        </span>
      </div>
      <a
        href="https://smith.langchain.com"
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-1 text-blue-600 hover:text-blue-700 font-medium"
      >
        LangSmith
        <ExternalLink className="w-3 h-3" />
      </a>
    </div>
  )
}
