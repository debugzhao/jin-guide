'use client'

import { useEffect, useRef } from 'react'
import { ExternalLink } from 'lucide-react'
import { useAppStore } from '@/lib/store'
import DebugEventRow from './DebugEventRow'

const FILTERS: { value: 'all' | 'node' | 'tool' | 'error'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'node', label: '仅 node' },
  { value: 'tool', label: '仅 tool' },
  { value: 'error', label: '仅异常' },
]

function matchesFilter(type: string, status: unknown, filter: string): boolean {
  if (filter === 'all') return true
  if (filter === 'node') return type === 'node_started' || type === 'node_completed'
  if (filter === 'tool') return type === 'tool_called'
  if (filter === 'error') {
    return (
      type === 'degraded' ||
      type === 'circuit_breaker' ||
      String(status).toUpperCase() === 'ERROR'
    )
  }
  return true
}

interface Props {
  traceUrl: string | null
  connectionError: string | null
  onRetryConnection: () => void
}

export default function DebugEventTimeline({ traceUrl, connectionError, onRetryConnection }: Props) {
  const { debugEvents, timelineFilter, setTimelineFilter, isAutoScroll, setAutoScroll } = useAppStore()
  const bottomRef = useRef<HTMLDivElement>(null)

  const filtered = debugEvents.filter((e) => matchesFilter(e.type, e.raw.status, timelineFilter))

  useEffect(() => {
    if (isAutoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [filtered.length, isAutoScroll])

  return (
    <div className="w-[320px] flex-shrink-0 border-l border-gray-200 bg-white flex flex-col h-full">
      <div className="px-3 py-2 border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-semibold text-gray-700">事件时间线</span>
          <label className="flex items-center gap-1 text-[10px] text-gray-500">
            <input type="checkbox" checked={isAutoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
            自动滚动
          </label>
        </div>
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setTimelineFilter(f.value)}
              className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                timelineFilter === f.value ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {connectionError && (
          <div className="mx-2 my-2 px-2 py-2 rounded bg-red-50 text-[11px] text-red-700 flex items-center justify-between">
            <span>连接失败，{connectionError}</span>
            <button onClick={onRetryConnection} className="underline font-medium flex-shrink-0 ml-2">
              重试
            </button>
          </div>
        )}
        {filtered.length === 0 && !connectionError && (
          <p className="text-[11px] text-gray-400 text-center py-6">暂无事件</p>
        )}
        {filtered.map((e) => (
          <DebugEventRow key={e.id} event={e} />
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="px-3 py-2 border-t border-gray-100 flex-shrink-0">
        <button
          disabled={!traceUrl}
          onClick={() => traceUrl && window.open(traceUrl, '_blank')}
          className="w-full flex items-center justify-center gap-1.5 text-xs font-medium text-blue-600 disabled:text-gray-300 hover:text-blue-700 py-1.5"
        >
          在 LangSmith 查看
          <ExternalLink className="w-3 h-3" />
        </button>
      </div>
    </div>
  )
}
