'use client'

import { useEffect, useState } from 'react'
import { Menu } from 'lucide-react'
import LoginSheet from '@/components/ui/LoginSheet'
import SidebarNav from '@/components/layout/SidebarNav'
import WorkspaceShell from '@/components/layout/WorkspaceShell'
import ConversationStream, { type Stage } from '@/components/workspace/ConversationStream'
import LiveReportPanel from '@/components/report/LiveReportPanel'
import { api } from '@/lib/api'
import { useAppStore, type CurrentUser } from '@/lib/store'

const APP_BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || ''

export interface InitialAuthState {
  checked: boolean
  user: CurrentUser | null
}

/** 原生 History API 不感知 Next basePath，必须显式补上子路径部署前缀。 */
function appUrl(path: `/${string}`): string {
  return `${APP_BASE_PATH}${path}`
}

/** Chat-first 首页的客户端交互层；首屏登录态由服务端 page.tsx 注入。 */
export default function HomeClient({ initialAuth }: { initialAuth: InitialAuthState }) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [conversationKey, setConversationKey] = useState(0)
  const [stage, setStage] = useState<Stage>('idle')
  const [reportId, setReportId] = useState<string | null>(null)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const {
    setUser,
    clearUser,
    setCurrentIntakeConversationId,
    loginModalOpen,
    setLoginModalOpen,
  } = useAppStore()

  useEffect(() => {
    if (initialAuth.checked) {
      if (initialAuth.user) setUser(initialAuth.user)
      else clearUser()
      return
    }
    api.me().then(setUser).catch(() => clearUser())
  }, [initialAuth, setUser, clearUser])

  const handleReportReady = (id: string) => {
    setReportId(id)
    if (id !== 'demo-report') {
      window.history.replaceState(null, '', appUrl(`/reports/${id}`))
    }
  }

  const handleNewConversation = () => {
    setReportId(null)
    setStage('idle')
    setRightCollapsed(false)
    setMobileSidebarOpen(false)
    setCurrentIntakeConversationId(null)
    window.history.replaceState(null, '', appUrl('/'))
    setConversationKey((k) => k + 1)
  }

  const handleSelectConversation = (conversationId: string) => {
    setReportId(null)
    setStage('idle')
    setRightCollapsed(false)
    setMobileSidebarOpen(false)
    setCurrentIntakeConversationId(conversationId)
    window.history.replaceState(null, '', appUrl('/'))
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
            onLoginClick={() => setLoginModalOpen(true)}
            onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
            initialUser={initialAuth.user}
            initialAuthChecked={initialAuth.checked}
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

      <LoginSheet
        isOpen={loginModalOpen}
        onClose={() => setLoginModalOpen(false)}
        onSuccess={() => setLoginModalOpen(false)}
      />
    </div>
  )
}
