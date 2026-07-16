'use client'

import { useEffect, useState } from 'react'
import { Menu } from 'lucide-react'
import LoginSheet from '@/components/ui/LoginSheet'
import SidebarNav from '@/components/layout/SidebarNav'
import WorkspaceShell from '@/components/layout/WorkspaceShell'
import ConversationStream, { type Stage } from '@/components/workspace/ConversationStream'
import LiveReportPanel from '@/components/report/LiveReportPanel'
import { api } from '@/lib/api'
import { useAppStore } from '@/lib/store'

/**
 * 首屏即 Chat-first AI 对话（docs/frontend-prd-v2.md §Chat-first 建档入口）。
 * 左侧对话流承载纯聊天 → 建档 → 生成过程 → 报告问答四个阶段；报告栏只在
 * idle 之后才出现（避免纯聊天阶段就摊开一个空状态报告卡片撑开布局）。
 * 拿到 report_id 后用 history.replaceState 把地址栏无刷新切换为
 * /reports/[id]——不触发 Next 路由导航，避免整颗组件树被卸载重挂载
 * （frontend-prd-v2.md §4.2「拿到可分享的 report_id 后地址栏无刷新切换」）。
 */
export default function HomePage() {
  const [loginOpen, setLoginOpen] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [conversationKey, setConversationKey] = useState(0)
  const [stage, setStage] = useState<Stage>('idle')
  const [reportId, setReportId] = useState<string | null>(null)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const { setUser, clearUser, setCurrentIntakeConversationId } = useAppStore()

  useEffect(() => {
    api.me().then(setUser).catch(() => clearUser())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleReportReady = (id: string) => {
    setReportId(id)
    if (id !== 'demo-report') {
      window.history.replaceState(null, '', `/reports/${id}`)
    }
  }

  const handleNewConversation = () => {
    setReportId(null)
    setStage('idle')
    setRightCollapsed(false)
    setMobileSidebarOpen(false)
    setCurrentIntakeConversationId(null)
    window.history.replaceState(null, '', '/')
    setConversationKey((k) => k + 1)
  }

  /** 侧栏点击某条历史会话：切到该会话继续聊，同一套 remount 机制，见 handleNewConversation */
  const handleSelectConversation = (conversationId: string) => {
    setReportId(null)
    setStage('idle')
    setRightCollapsed(false)
    setMobileSidebarOpen(false)
    setCurrentIntakeConversationId(conversationId)
    window.history.replaceState(null, '', '/')
    setConversationKey((k) => k + 1)
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="sticky top-0 z-30 bg-white/90 backdrop-blur border-b border-[#E2E8F0] px-4 py-2.5 flex-shrink-0 lg:hidden">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setMobileSidebarOpen(true)}
            className="p-1.5 -ml-1.5 text-[#64748B] hover:text-[#0F172A]"
            aria-label="打开菜单"
          >
            <Menu className="w-5 h-5" />
          </button>
          <h1 className="text-base font-bold text-[#0F172A]">问津 <span className="text-[#1E40AF]">Agent</span></h1>
        </div>
      </header>

      <WorkspaceShell
        sidebar={
          <SidebarNav
            onNewConversation={handleNewConversation}
            onSelectConversation={handleSelectConversation}
            onLoginClick={() => setLoginOpen(true)}
            onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
          />
        }
        left={<ConversationStream key={conversationKey} onReportReady={handleReportReady} onStageChange={setStage} />}
        right={<LiveReportPanel reportId={reportId} />}
        hasRight={stage !== 'idle'}
        rightCollapsed={rightCollapsed}
        onToggleRight={() => setRightCollapsed((v) => !v)}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        mobileSidebarOpen={mobileSidebarOpen}
        onCloseMobileSidebar={() => setMobileSidebarOpen(false)}
      />

      <LoginSheet isOpen={loginOpen} onClose={() => setLoginOpen(false)} onSuccess={() => setLoginOpen(false)} />
    </div>
  )
}
