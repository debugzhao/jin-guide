'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { adminApi } from '@/lib/adminApi'
import { useAppStore } from '@/lib/store'
import QueryProvider from '@/lib/QueryProvider'
import DebugMetricsBar from './DebugMetricsBar'
import DebugRunList from './DebugRunList'
import LangGraphTopology from './LangGraphTopology'
import NodeDetailPanel from './NodeDetailPanel'
import DebugEventTimeline from './DebugEventTimeline'

// Admin Debug 控制台 — 独立路由 /admin/debug，仅 role=admin 可访问（见 page.tsx 的角色校验）。
// 桌面端三栏布局：Run 列表 + LangGraph 拓扑图 + 事件时间线。配色刻意保留浅色高对比
// （不跟随 v2.3 深色主题改版）：作为纯诊断工具，优先保证开发者快速识别状态。

function DebugConsoleBody() {
  const { selectedRunId, applyDebugEvent, markRunningNodesFailed, debugEvents } = useAppStore()
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [expiredHint, setExpiredHint] = useState(false)

  const { data: runDetail } = useQuery({
    queryKey: ['admin', 'run', selectedRunId],
    queryFn: () => adminApi.getRun(selectedRunId as string),
    enabled: !!selectedRunId,
  })

  useEffect(() => {
    setSelectedNode(null)
    setConnectionError(null)
    setExpiredHint(false)
    if (!selectedRunId) return

    const close = adminApi.streamDebugEvents(selectedRunId, {
      onConnected: () => setConnectionError(null),
      onEvent: (type, data) => {
        setConnectionError(null)
        applyDebugEvent(type, data)
      },
      onStreamEnd: () => {
        const { debugEvents: current } = useAppStore.getState()
        if (current.length === 0) setExpiredHint(true)
        adminApi
          .getRun(selectedRunId)
          .then((run) => {
            if (run.status === 'failed' || run.status === 'timeout') markRunningNodesFailed()
          })
          .catch(() => {})
      },
      onError: (msg) => setConnectionError(msg),
    })

    return () => close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId])

  const handleRetryConnection = () => {
    if (!selectedRunId) return
    setConnectionError(null)
    const { setSelectedRunId } = useAppStore.getState()
    setSelectedRunId(selectedRunId)
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      <DebugRunList />

      <div className="flex-1 flex flex-col overflow-hidden">
        {expiredHint && debugEvents.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-6">
            <p className="text-sm text-gray-500">该 run 的 Debug 事件已过期（超过 7 天保留期），请直接查看 LangSmith</p>
            {runDetail?.trace_url && (
              <a
                href={runDetail.trace_url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-blue-600 underline"
              >
                跳转 LangSmith
              </a>
            )}
          </div>
        ) : (
          <LangGraphTopology selectedNode={selectedNode} onSelectNode={setSelectedNode} />
        )}
        {selectedNode && !expiredHint && (
          <NodeDetailPanel nodeName={selectedNode} onClose={() => setSelectedNode(null)} />
        )}
      </div>

      <DebugEventTimeline
        traceUrl={runDetail?.trace_url ?? null}
        connectionError={connectionError}
        onRetryConnection={handleRetryConnection}
      />
    </div>
  )
}

export default function DebugConsole() {
  const router = useRouter()

  return (
    <div className="fixed inset-0 bg-white flex flex-col">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-200 bg-white flex-shrink-0">
        <button
          onClick={() => router.push('/')}
          className="p-1.5 rounded-btn text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          aria-label="返回"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="text-sm font-semibold text-gray-900">🔧 Admin Debug 控制台</h1>
      </div>

      <div className="md:hidden flex-1 flex items-center justify-center px-8 text-center">
        <p className="text-sm text-gray-500">请在桌面端使用 Debug 控制台</p>
      </div>

      <div className="hidden md:flex md:flex-col flex-1 overflow-hidden">
        <QueryProvider>
          <DebugMetricsBar />
          <DebugConsoleBody />
        </QueryProvider>
      </div>
    </div>
  )
}
