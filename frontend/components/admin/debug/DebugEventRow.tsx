'use client'

import type { DebugEvent } from '@/types'

function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('zh-CN', { hour12: false }) + `.${String(d.getMilliseconds()).padStart(3, '0')}`
}

function rowStyle(event: DebugEvent): { border?: string; bg?: string; text?: string; italic?: boolean } {
  const status = String(event.raw.status ?? '').toUpperCase()
  switch (event.type) {
    case 'node_started':
      return { border: 'border-l-blue-500' }
    case 'node_completed':
      if (status === 'FAILED' || status === 'ERROR') return { border: 'border-l-red-500' }
      return { border: 'border-l-green-500' }
    case 'tool_called':
      return { text: status === 'ERROR' ? 'text-red-600' : 'text-green-700' }
    case 'degraded':
      return { bg: 'bg-amber-50' }
    case 'circuit_breaker':
      return { bg: 'bg-red-50' }
    case 'parallel_fan_out':
    case 'parallel_fan_in':
      return { text: 'text-purple-600', italic: true }
    case 'reflection_iteration':
      return { border: 'border-l-purple-500' }
    case 'state_checkpoint':
      return { bg: 'bg-gray-50' }
    default:
      return {}
  }
}

function summarize(event: DebugEvent): string {
  const d = event.raw
  switch (event.type) {
    case 'node_started':
      return String(d.node ?? '')
    case 'node_completed':
      return `${d.node} · ${typeof d.latency_ms === 'number' ? `${d.latency_ms}ms` : ''}`
    case 'tool_called':
      return `${d.tool} · ${typeof d.latency_ms === 'number' ? `${d.latency_ms}ms` : ''}${d.result_summary ? ` (${d.result_summary})` : ''}`
    case 'degraded':
      return `${d.from} → ${d.to}`
    case 'circuit_breaker':
      return `${d.tool} → ${d.state}`
    case 'parallel_fan_out':
      return `→ [${Array.isArray(d.from) ? d.from.join(', ') : d.node}]`
    case 'parallel_fan_in':
      return `← [${Array.isArray(d.from) ? d.from.join(', ') : ''}]`
    case 'reflection_iteration':
      return `第 ${d.iteration} 轮 · ${d.passed ? '通过' : '未通过'}`
    default:
      return JSON.stringify(d)
  }
}

export default function DebugEventRow({ event }: { event: DebugEvent }) {
  const style = rowStyle(event)
  return (
    <div
      className={`flex items-baseline gap-2 px-2 py-1 text-[11px] border-l-2 ${style.border ?? 'border-l-transparent'} ${style.bg ?? ''}`}
    >
      <span className="text-gray-400 font-mono flex-shrink-0">{formatTime(event.ts)}</span>
      <span className="text-gray-500 flex-shrink-0 w-[110px] truncate">{event.type}</span>
      <span className={`truncate ${style.text ?? 'text-gray-700'} ${style.italic ? 'italic' : ''}`}>
        {summarize(event)}
      </span>
    </div>
  )
}
