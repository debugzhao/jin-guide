'use client'

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { adminApi } from '@/lib/adminApi'
import { useAppStore } from '@/lib/store'
import QueryProvider from '@/lib/QueryProvider'
import DebugMetricsBar from '@/components/admin/debug/DebugMetricsBar'
import DebugRunList from '@/components/admin/debug/DebugRunList'
import LangGraphTopology from '@/components/admin/debug/LangGraphTopology'
import NodeDetailPanel from '@/components/admin/debug/NodeDetailPanel'
import DebugEventTimeline from '@/components/admin/debug/DebugEventTimeline'

type AuthState = 'checking' | 'ok' | 'forbidden'

function AdminDebugConsole() {
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
    // Re-trigger the effect by bouncing selectedRunId through itself via the store setter
    if (!selectedRunId) return
    setConnectionError(null)
    const { setSelectedRunId } = useAppStore.getState()
    setSelectedRunId(selectedRunId)
  }

  return (
    <div className="flex flex-col h-screen">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-200 bg-white flex-shrink-0">
        <h1 className="text-sm font-semibold text-gray-900">🔧 Admin Debug 控制台</h1>
      </div>
      <DebugMetricsBar />

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
    </div>
  )
}

export default function AdminDebugShell() {
  const [auth, setAuth] = useState<AuthState>('checking')

  useEffect(() => {
    api
      .me()
      .then((me) => setAuth(me.role === 'admin' ? 'ok' : 'forbidden'))
      .catch(() => setAuth('forbidden'))
  }, [])

  return (
    <>
      {/* Debug 是开发工具，不做移动适配 — PRD §8.11 */}
      <div className="md:hidden flex items-center justify-center h-screen px-8 text-center">
        <p className="text-sm text-gray-500">请在桌面端使用 Debug 控制台</p>
      </div>

      <div className="hidden md:block h-screen">
        {auth === 'checking' && (
          <div className="flex items-center justify-center h-full text-sm text-gray-400">加载中...</div>
        )}
        {auth === 'forbidden' && (
          <div className="flex items-center justify-center h-full text-sm text-gray-500">
            403 · 需要管理员权限，无法查看此页面
          </div>
        )}
        {auth === 'ok' && (
          <QueryProvider>
            <AdminDebugConsole />
          </QueryProvider>
        )}
      </div>
    </>
  )
}
