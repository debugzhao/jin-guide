'use client'

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { adminApi } from '@/lib/adminApi'
import { useAppStore } from '@/lib/store'
import QueryProvider from '@/lib/QueryProvider'
import DebugMetricsBar from './DebugMetricsBar'
import DebugRunList from './DebugRunList'
import LangGraphTopology from './LangGraphTopology'
import NodeDetailPanel from './NodeDetailPanel'
import DebugEventTimeline from './DebugEventTimeline'

// Admin Debug 控制台，改造为首页可从任意入口打开的抽屉，不做角色限制（任何访客可用）。
// 交互形式选用右侧全高大尺寸 Drawer 而非居中 Modal / 底部 BottomSheet：内容是 PRD §8.11
// 定义的三栏桌面布局（Run 列表 + 拓扑图 + 事件时间线），Modal 常见的 420-600px 宽度装不下
// 三栏，BottomSheet 的高度受限语义也不适合宽版布局；右侧撑满高度的 Drawer 观感上像从主页
// 浮出一个工作台，且与已有 ChatPanel 的桌面 Drawer 模式一致。

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

export default function DebugDrawer() {
  const isOpen = useAppStore((s) => s.isDebugDrawerOpen)
  const closeDebugDrawer = useAppStore((s) => s.closeDebugDrawer)

  if (!isOpen) return null

  return (
    <>
      {/* Mobile: Bottom Sheet overlay, mirrors ChatPanel's pattern */}
      <div className="fixed inset-0 bg-black/30 z-40 md:hidden" onClick={closeDebugDrawer} />

      <div
        className="
          fixed z-50 bg-white flex flex-col shadow-xl
          /* mobile: bottom sheet with a desktop-only notice inside */
          bottom-0 left-0 right-0 rounded-t-2xl h-[70vh]
          /* desktop: wide right drawer, full height */
          md:top-0 md:right-0 md:bottom-0 md:left-auto md:rounded-none md:border-l md:border-gray-200
          md:w-[92vw] md:max-w-[1280px]
        "
      >
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-200 bg-white flex-shrink-0">
          <h1 className="text-sm font-semibold text-gray-900">🔧 Debug 控制台</h1>
          <button
            onClick={closeDebugDrawer}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            aria-label="关闭"
          >
            <X className="w-4 h-4" />
          </button>
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
    </>
  )
}
