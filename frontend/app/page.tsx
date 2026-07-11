'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Button from '@/components/ui/Button'
import LoginSheet from '@/components/ui/LoginSheet'
import UserMenu from '@/components/ui/UserMenu'
import WorkspaceShell from '@/components/layout/WorkspaceShell'
import ConversationStream from '@/components/workspace/ConversationStream'
import LiveReportPanel from '@/components/report/LiveReportPanel'
import { api } from '@/lib/api'
import { useAppStore } from '@/lib/store'

/**
 * 首屏即 AI 对话建档（F2, frontend-prd-v2.md §6.1）。左侧对话流承载建档、
 * 生成过程、报告问答三个阶段；右侧实时报告面板从空状态随对话推进渲染出
 * 基础版报告。拿到 report_id 后用 history.replaceState 把地址栏无刷新切换为
 * /reports/[id]——不触发 Next 路由导航，避免整颗组件树被卸载重挂载
 * （frontend-prd-v2.md §4.2「拿到可分享的 report_id 后地址栏无刷新切换」）。
 */
export default function HomePage() {
  const router = useRouter()
  const [loginOpen, setLoginOpen] = useState(false)
  const [reportId, setReportId] = useState<string | null>(null)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const { user, authChecked, setUser, clearUser } = useAppStore()

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

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="sticky top-0 z-30 bg-[#040128]/90 backdrop-blur border-b border-white/10 px-4 py-3 flex-shrink-0">
        <div className="max-w-screen-xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-[#F1F5F9]">问津 <span className="text-[#A78BFA]">Agent</span></h1>
            <p className="text-xs text-[#9CA3C4] mt-0.5">AI 志愿决策助理，全程陪你完成建档到报告</p>
          </div>
          <div className="flex items-center gap-2">
            {reportId && (
              <button
                onClick={() => router.push('/reports')}
                className="text-xs text-[#9CA3C4] hover:text-[#F1F5F9] px-2 py-1"
              >
                历史报告
              </button>
            )}
            {authChecked && (
              user ? <UserMenu /> : (
                <Button variant="ghost" size="sm" onClick={() => setLoginOpen(true)}>
                  登录
                </Button>
              )
            )}
          </div>
        </div>
      </header>

      <WorkspaceShell
        left={<ConversationStream onReportReady={handleReportReady} />}
        right={<LiveReportPanel reportId={reportId} />}
        rightCollapsed={rightCollapsed}
        onToggleRight={() => setRightCollapsed((v) => !v)}
      />

      <LoginSheet isOpen={loginOpen} onClose={() => setLoginOpen(false)} onSuccess={() => setLoginOpen(false)} />
    </div>
  )
}
