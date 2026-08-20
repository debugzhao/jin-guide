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
  /** 并行扇出/扇入边在其分支处于激活状态时会有流动效果 */
  active?: boolean
  /** 递增这个值（例如迭代次数）可以重放一次性的重试闪烁效果 */
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
    // 从 reflection 向左弯曲回到 report——画成看得见的重试环，而不是直线重叠
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

/** 共享的 <defs> 箭头——每个 <svg> 画布只需渲染一次，且要在任何 TopologyEdge 之前渲染 */
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
