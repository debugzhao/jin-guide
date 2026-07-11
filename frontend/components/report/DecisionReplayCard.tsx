'use client'

import { useState } from 'react'
import { ChevronDown, ChevronUp, History } from 'lucide-react'
import type { ApiRunSummary } from '@/lib/reportMapping'

interface Props {
  runSummary: ApiRunSummary | null
}

/**
 * 「AI 是如何得出这份方案的」决策过程回放卡片 (frontend-prd-v2.md §6.2)。
 * 只读回放 `reports.run_summary_json`，不重新调用 Agent。默认折叠。
 */
export default function DecisionReplayCard({ runSummary }: Props) {
  const [expanded, setExpanded] = useState(false)
  if (!runSummary) return null

  const nodeTimings = runSummary.node_timings ?? {}
  const degradedAgents = runSummary.degraded_agents ?? []
  const reflectionIterations = runSummary.reflection_iterations ?? 0

  return (
    <div className="wj-glass-card rounded-card overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm text-[#F1F5F9]">
          <History className="w-4 h-4 text-[#A78BFA]" />
          AI 是如何得出这份方案的
        </span>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-[#9CA3C4]" />
        ) : (
          <ChevronDown className="w-4 h-4 text-[#9CA3C4]" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-3 space-y-1.5 text-xs text-[#9CA3C4]">
          <p>并行处理过检索招生数据 + 校验选科/体检/批次规则两项任务</p>
          <p>
            AI 自我检查{reflectionIterations > 0 ? `修正了 ${reflectionIterations} 轮` : '一次通过，未触发修正'}
          </p>
          {degradedAgents.length > 0 ? (
            <p>检索环节曾切换备用数据源：{degradedAgents.join('、')}</p>
          ) : (
            <p>全程未发生降级，所有节点均正常完成</p>
          )}
          {Object.keys(nodeTimings).length > 0 && (
            <div className="pt-1 space-y-0.5">
              {Object.entries(nodeTimings).map(([node, ms]) => (
                <p key={node}>{node}：{Math.round(ms)}ms</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
