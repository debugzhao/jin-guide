'use client'

export type EdgeKind = 'main' | 'parallel' | 'retry' | 'conditional'

interface Point {
  x: number
  y: number
}

interface Props {
  from: Point
  to: Point
  kind: EdgeKind
  /** Parallel fan-out/in edges flow while their branch is active */
  active?: boolean
  /** Bump this (e.g. iteration count) to replay the one-shot retry flash */
  flashKey?: number | string
}

const STROKE: Record<EdgeKind, string> = {
  main: '#94A3B8',
  parallel: '#94A3B8',
  retry: '#7C3AED',
  conditional: '#94A3B8',
}

export default function TopologyEdge({ from, to, kind, active, flashKey }: Props) {
  const stroke = STROKE[kind]
  const dashed = kind === 'retry' || kind === 'conditional'
  const markerId = kind === 'retry' ? 'wj-arrow-retry' : 'wj-arrow-main'

  if (kind === 'retry') {
    // Bow left from reflection back up to report — a visible retry loop, not a straight overlap.
    const bowX = Math.min(from.x, to.x) - 70
    const d = `M ${from.x} ${from.y} C ${bowX} ${from.y}, ${bowX} ${to.y}, ${to.x} ${to.y}`
    return (
      <path
        key={flashKey}
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={2}
        strokeDasharray="5,4"
        markerEnd={`url(#${markerId})`}
        className={flashKey !== undefined ? 'wj-edge-flash' : ''}
      />
    )
  }

  return (
    <line
      key={active ? `active-${flashKey}` : 'idle'}
      x1={from.x}
      y1={from.y}
      x2={to.x}
      y2={to.y}
      stroke={stroke}
      strokeWidth={2}
      strokeDasharray={dashed ? '5,4' : undefined}
      markerEnd={`url(#${markerId})`}
      className={active ? 'wj-edge-flow' : ''}
    />
  )
}

/** Shared <defs> arrowheads — render once per <svg> canvas, before any TopologyEdge. */
export function TopologyEdgeDefs() {
  return (
    <defs>
      <marker id="wj-arrow-main" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#94A3B8" />
      </marker>
      <marker id="wj-arrow-retry" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#7C3AED" />
      </marker>
    </defs>
  )
}
