'use client'

import { useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Share2 } from 'lucide-react'
import TopNav from '@/components/layout/TopNav'
import SidebarNav from '@/components/layout/SidebarNav'
import WorkspaceShell from '@/components/layout/WorkspaceShell'
import ChatColumn from '@/components/chat/ChatColumn'
import LiveReportPanel from '@/components/report/LiveReportPanel'
import { useAppStore } from '@/lib/store'

/**
 * 报告工作台 —— `/` 页面实时报告面板拿到可分享 report_id 后的独立路由呈现
 * （F2, frontend-prd-v2.md §6.2）：与 `/` 是同一套 WorkspaceShell/
 * LiveReportPanel/ReportCanvas 组件，区别只是这里直接从 report_id 进入，
 * 左侧对话栏直接是报告问答（不再经过建档/生成过程阶段），也是历史记录访问
 * 和分享链接的落地形态。
 */
export default function ReportWorkspacePage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const setCurrentIntakeConversationId = useAppStore((s) => s.setCurrentIntakeConversationId)

  const handleShare = async () => {
    try {
      await navigator.share({ title: '我的高考志愿方案', url: window.location.href })
    } catch {
      // 用户取消分享或浏览器不支持，静默忽略
    }
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <TopNav
        title="报告工作台"
        showBack
        onBack={() => router.push('/reports')}
        rightSlot={
          <button onClick={handleShare} className="p-2 rounded-btn text-[#64748B] hover:text-[#0F172A] hover:bg-[#F1F5F9]">
            <Share2 className="w-4.5 h-4.5" />
          </button>
        }
      />

      <WorkspaceShell
        sidebar={
          <SidebarNav
            onNewConversation={() => router.push('/')}
            onSelectConversation={(conversationId) => {
              setCurrentIntakeConversationId(conversationId)
              router.push('/')
            }}
            onLoginClick={() => router.push('/')}
          />
        }
        left={<ChatColumn reportId={id} />}
        right={<LiveReportPanel reportId={id} />}
        hasRight
        rightCollapsed={rightCollapsed}
        onToggleRight={() => setRightCollapsed((v) => !v)}
        mobileSidebarOpen={false}
        onCloseMobileSidebar={() => {}}
      />
    </div>
  )
}
