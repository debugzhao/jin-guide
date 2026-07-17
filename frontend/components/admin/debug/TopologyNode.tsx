'use client'

import type { NodeStatus } from '@/types'

export type NodeKind = 'llm' | 'deterministic' | 'llm_judge'

export interface NodeMeta {
  name: string
  label: string
  icon: string
  kind: NodeKind
}

const KIND_ACCENT: Record<NodeKind, string> = {
  llm: 'text-blue-500',
  deterministic: 'text-green-600',
  llm_judge: 'text-purple-600',
}

// PRD §8.11 status color table (frontend-prd.md)
const STATUS_STYLE: Record<NodeStatus, { border: string; bg: string; extra?: string }> = {
  pending: { border: 'border-slate-200', bg: 'bg-slate-50' },
  running: { border: 'border-blue-600', bg: 'bg-blue-50', extra: 'animate-pulse' },
  completed: { border: 'border-green-600', bg: 'bg-green-50' },
  degraded: { border: 'border-amber-600', bg: 'bg-amber-50' },
  failed: { border: 'border-red-600', bg: 'bg-red-50' },
  interrupted: { border: 'border-purple-600', bg: 'bg-purple-50', extra: 'animate-pulse' },
  skipped: { border: 'border-slate-200 border-dashed', bg: 'bg-slate-50 opacity-40' },
}

const STATUS_BADGE: Partial<Record<NodeStatus, string>> = {
  completed: '✓',
  degraded: '⚠',
  failed: '✗',
}

interface Props {
  meta: NodeMeta
  status: NodeStatus
  latencyMs?: number
  iteration?: number
  x: number
  y: number
  width: number
  height: number
  selected: boolean
  onClick: () => void
}

export default function TopologyNode({
  meta,
  status,
  latencyMs,
  iteration,
  x,
  y,
  width,
  height,
  selected,
  onClick,
}: Props) {
  const style = STATUS_STYLE[status]
  const badge = STATUS_BADGE[status]

  return (
    <button
      onClick={onClick}
      style={{ left: x - width / 2, top: y, width, height }}
      className={`absolute flex flex-col items-center justify-center rounded-card border-2 transition-colors ${style.border} ${style.bg} ${style.extra ?? ''} ${
        selected ? 'ring-2 ring-offset-1 ring-blue-400' : ''
      }`}
    >
      {badge && (
        <span className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-white flex items-center justify-center text-[10px] shadow border border-gray-100">
          {badge}
        </span>
      )}
      {typeof iteration === 'number' && (
        <span className="absolute -right-2 top-1/2 -translate-y-1/2 translate-x-full text-[10px] text-purple-600 font-medium whitespace-nowrap pl-1">
          {iteration}/3
        </span>
      )}
      <span className={`text-base leading-none ${KIND_ACCENT[meta.kind]}`}>{meta.icon}</span>
      <span className="text-[11px] font-medium text-gray-800 mt-0.5">{meta.label}</span>
      {status === 'completed' && typeof latencyMs === 'number' && (
        <span className="text-[9px] text-gray-400">{(latencyMs / 1000).toFixed(1)}s</span>
      )}
    </button>
  )
}
