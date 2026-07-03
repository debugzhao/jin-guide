'use client'

import { useAppStore } from '@/lib/store'
import TopologyNode, { type NodeMeta } from './TopologyNode'
import TopologyEdge, { TopologyEdgeDefs } from './TopologyEdge'

// ── Static layout (PRD §8.11 — "不引入 ReactFlow", fixed CSS-grid-like canvas) ──
// Node set matches the actual compiled LangGraph (backend/app/agent/graph.py), 7
// nodes. profile_agent/human_review_node/deliver from the PRD's original 10-node
// design don't exist post-v1.1 HITL removal (see CLAUDE.md) and are intentionally
// omitted — a node that never receives a debug event would just sit permanently
// gray, which misleads more than it helps.

const CANVAS_WIDTH = 400
const CANVAS_HEIGHT = 760
const NODE_W = 128
const NODE_H = 54
const COL_LEFT = 100
const COL_MID = 200
const COL_RIGHT = 300

const NODE_META: Record<string, NodeMeta> = {
  data_resolver: { name: 'data_resolver', label: '数据版本', icon: '🗄️', kind: 'deterministic' },
  retrieval_agent: { name: 'retrieval_agent', label: '证据检索', icon: '🔍', kind: 'llm' },
  policy_rule_agent: { name: 'policy_rule_agent', label: '规则校验', icon: '✅', kind: 'deterministic' },
  recommendation: { name: 'recommendation', label: '方案生成', icon: '📊', kind: 'deterministic' },
  risk: { name: 'risk', label: '风险体检', icon: '⚠️', kind: 'deterministic' },
  report: { name: 'report', label: '报告生成', icon: '📝', kind: 'llm' },
  reflection: { name: 'reflection', label: '合规自检', icon: '🔄', kind: 'llm_judge' },
}

const LAYOUT: Record<string, { x: number; y: number }> = {
  data_resolver: { x: COL_MID, y: 20 },
  retrieval_agent: { x: COL_LEFT, y: 140 },
  policy_rule_agent: { x: COL_RIGHT, y: 140 },
  recommendation: { x: COL_MID, y: 260 },
  risk: { x: COL_MID, y: 360 },
  report: { x: COL_MID, y: 460 },
  reflection: { x: COL_MID, y: 560 },
}
const END_POS = { x: COL_MID, y: 670 }

function center(name: string, edge: 'top' | 'bottom' | 'left' | 'right' = 'bottom') {
  const p = LAYOUT[name] ?? END_POS
  const halfW = NODE_W / 2
  const halfH = NODE_H / 2
  switch (edge) {
    case 'top':
      return { x: p.x, y: p.y }
    case 'bottom':
      return { x: p.x, y: p.y + NODE_H }
    case 'left':
      return { x: p.x - halfW, y: p.y + halfH }
    case 'right':
      return { x: p.x + halfW, y: p.y + halfH }
  }
}

interface Props {
  selectedNode: string | null
  onSelectNode: (name: string) => void
}

export default function LangGraphTopology({ selectedNode, onSelectNode }: Props) {
  const nodeStates = useAppStore((s) => s.nodeStates)

  const isRunning = (name: string) => nodeStates[name]?.status === 'running'
  const reflectionIteration = nodeStates.reflection?.iteration

  return (
    <div className="relative flex-1 overflow-auto bg-slate-50/50 min-h-[760px]" style={{ minWidth: CANVAS_WIDTH }}>
      <div className="relative mx-auto my-6" style={{ width: CANVAS_WIDTH, height: CANVAS_HEIGHT }}>
        {/* Parallel-execution grouping box behind retrieval/policy_rule nodes */}
        <div
          className="absolute rounded-2xl bg-slate-100/70 border border-dashed border-slate-300"
          style={{ left: 20, top: 118, width: CANVAS_WIDTH - 40, height: NODE_H + 40 }}
        >
          <span className="absolute -top-2.5 left-3 bg-slate-50 px-1.5 text-[10px] text-slate-400">
            并行执行
          </span>
        </div>

        <svg width={CANVAS_WIDTH} height={CANVAS_HEIGHT} className="absolute inset-0 pointer-events-none">
          <TopologyEdgeDefs />
          {/* data_resolver → [retrieval_agent, policy_rule_agent] (fan-out) */}
          <TopologyEdge
            kind="parallel"
            from={center('data_resolver', 'bottom')}
            to={center('retrieval_agent', 'top')}
            active={isRunning('retrieval_agent')}
          />
          <TopologyEdge
            kind="parallel"
            from={center('data_resolver', 'bottom')}
            to={center('policy_rule_agent', 'top')}
            active={isRunning('policy_rule_agent')}
          />
          {/* [retrieval_agent, policy_rule_agent] → recommendation (fan-in) */}
          <TopologyEdge
            kind="parallel"
            from={center('retrieval_agent', 'bottom')}
            to={center('recommendation', 'top')}
            active={isRunning('recommendation')}
          />
          <TopologyEdge
            kind="parallel"
            from={center('policy_rule_agent', 'bottom')}
            to={center('recommendation', 'top')}
            active={isRunning('recommendation')}
          />
          <TopologyEdge kind="main" from={center('recommendation', 'bottom')} to={center('risk', 'top')} />
          <TopologyEdge kind="main" from={center('risk', 'bottom')} to={center('report', 'top')} />
          <TopologyEdge kind="main" from={center('report', 'bottom')} to={center('reflection', 'top')} />
          {/* Retry loop: reflection → report (bows left), replays on each reflection_iteration */}
          <TopologyEdge
            kind="retry"
            from={center('reflection', 'left')}
            to={center('report', 'left')}
            flashKey={reflectionIteration}
          />
          {/* Conditional terminal edge: reflection → END */}
          <TopologyEdge kind="conditional" from={center('reflection', 'bottom')} to={{ x: END_POS.x, y: END_POS.y }} />
        </svg>

        {Object.entries(NODE_META).map(([name, meta]) => {
          const pos = LAYOUT[name]
          const state = nodeStates[name] ?? { status: 'pending' as const }
          return (
            <TopologyNode
              key={name}
              meta={meta}
              status={state.status}
              latencyMs={state.latencyMs}
              iteration={name === 'reflection' ? state.iteration : undefined}
              x={pos.x}
              y={pos.y}
              width={NODE_W}
              height={NODE_H}
              selected={selectedNode === name}
              onClick={() => onSelectNode(name)}
            />
          )
        })}

        <div
          className="absolute flex items-center justify-center rounded-full border-2 border-slate-300 bg-white text-[11px] text-slate-500"
          style={{ left: END_POS.x - 32, top: END_POS.y, width: 64, height: 40 }}
        >
          结束
        </div>
      </div>
    </div>
  )
}
