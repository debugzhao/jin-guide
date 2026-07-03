'use client'

import { X, Wrench, AlertTriangle, Zap } from 'lucide-react'
import { useAppStore } from '@/lib/store'

const NODE_LABELS: Record<string, string> = {
  data_resolver: '数据版本',
  retrieval_agent: '证据检索',
  policy_rule_agent: '规则校验',
  recommendation: '方案生成',
  risk: '风险体检',
  report: '报告生成',
  reflection: '合规自检',
}

interface Props {
  nodeName: string
  onClose: () => void
}

export default function NodeDetailPanel({ nodeName, onClose }: Props) {
  const nodeState = useAppStore((s) => s.nodeStates[nodeName])
  const debugEvents = useAppStore((s) => s.debugEvents)

  const nodeEvents = debugEvents.filter((e) => e.node === nodeName)
  const toolCalls = nodeEvents.filter((e) => e.type === 'tool_called')
  const degradedEvents = nodeEvents.filter((e) => e.type === 'degraded')
  const breakerEvents = nodeEvents.filter((e) => e.type === 'circuit_breaker')
  const reflectionRounds =
    nodeName === 'reflection' ? debugEvents.filter((e) => e.type === 'reflection_iteration') : []

  return (
    <div className="border-t border-gray-200 bg-white px-4 py-3 max-h-[260px] overflow-y-auto flex-shrink-0">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-gray-900">
          {NODE_LABELS[nodeName] ?? nodeName}
          <span className="ml-2 text-xs font-normal text-gray-400">
            {nodeState?.status ?? 'pending'}
            {typeof nodeState?.latencyMs === 'number' && ` · ${(nodeState.latencyMs / 1000).toFixed(1)}s`}
          </span>
        </p>
        <button onClick={onClose} className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {toolCalls.length === 0 && degradedEvents.length === 0 && breakerEvents.length === 0 && reflectionRounds.length === 0 && (
        <p className="text-xs text-gray-400">该节点暂无工具调用记录</p>
      )}

      {toolCalls.length > 0 && (
        <div className="mb-2">
          <p className="text-[11px] font-medium text-gray-500 mb-1 flex items-center gap-1">
            <Wrench className="w-3 h-3" /> 工具调用
          </p>
          <ul className="space-y-1">
            {toolCalls.map((e) => {
              const d = e.raw
              const ok = String(d.status).toUpperCase() !== 'ERROR'
              return (
                <li key={e.id} className="flex items-center justify-between text-xs px-2 py-1 rounded bg-gray-50">
                  <span className={ok ? 'text-green-700' : 'text-red-700'}>{String(d.tool)}</span>
                  <span className="text-gray-400">
                    {typeof d.latency_ms === 'number' ? `${d.latency_ms}ms` : ''}
                    {d.result_summary ? ` · ${d.result_summary}` : ''}
                    {ok ? ' ✓' : ' ✗'}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {degradedEvents.length > 0 && (
        <div className="mb-2">
          <p className="text-[11px] font-medium text-amber-600 mb-1 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> 降级
          </p>
          <ul className="space-y-1">
            {degradedEvents.map((e) => (
              <li key={e.id} className="text-xs px-2 py-1 rounded bg-amber-50 text-amber-800">
                {String(e.raw.from)} → {String(e.raw.to)}
                {e.raw.reason ? `（${e.raw.reason}）` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      {breakerEvents.length > 0 && (
        <div className="mb-2">
          <p className="text-[11px] font-medium text-red-600 mb-1 flex items-center gap-1">
            <Zap className="w-3 h-3" /> 熔断状态
          </p>
          <ul className="space-y-1">
            {breakerEvents.map((e) => (
              <li key={e.id} className="text-xs px-2 py-1 rounded bg-red-50 text-red-800">
                {String(e.raw.tool)} → {String(e.raw.state)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {reflectionRounds.length > 0 && (
        <div>
          <p className="text-[11px] font-medium text-purple-600 mb-1">迭代记录</p>
          <ul className="space-y-1">
            {reflectionRounds.map((e) => (
              <li key={e.id} className="text-xs px-2 py-1 rounded bg-purple-50 text-purple-800">
                第 {String(e.raw.iteration)} 轮 · {e.raw.passed ? '通过' : '未通过'}
                {Array.isArray(e.raw.issues) && e.raw.issues.length > 0 ? `（${e.raw.issues.join('；')}）` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
