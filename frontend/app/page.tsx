'use client'

import { useEffect, useState } from 'react'
import { Compass, ClipboardCheck, BarChart2, Wrench } from 'lucide-react'
import EntryCard from '@/components/entry/EntryCard'
import Button from '@/components/ui/Button'
import LoginSheet from '@/components/ui/LoginSheet'
import UserMenu from '@/components/ui/UserMenu'
import DebugDrawer from '@/components/admin/debug/DebugDrawer'
import { api } from '@/lib/api'
import { useAppStore } from '@/lib/store'

export default function HomePage() {
  const [loginOpen, setLoginOpen] = useState(false)
  const { user, authChecked, setUser, clearUser, openDebugDrawer } = useAppStore()

  useEffect(() => {
    api.me().then(setUser).catch(() => clearUser())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="wj-shell min-h-screen bg-[#F8FAFC]">
      {/* Header */}
      <header className="wj-header bg-white border-b border-[#E2E8F0] px-4 py-4">
        <div className="wj-header-inner max-w-screen-md mx-auto flex items-center justify-between">
          <div>
            <h1 className="wj-title text-xl font-bold text-[#1E40AF]">问津 Agent</h1>
            <p className="wj-subtitle text-xs text-[#64748B] mt-0.5">AI 志愿决策助理，帮你稳上心仪大学</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={openDebugDrawer}
              className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-[#64748B] hover:text-[#1E40AF] hover:bg-[#EFF6FF] transition-colors"
              aria-label="打开 Debug 控制台"
              title="Debug 控制台"
            >
              <Wrench className="w-4 h-4" />
            </button>
            {authChecked && (user ? <UserMenu /> : (
              <Button variant="ghost" size="sm" onClick={() => setLoginOpen(true)}>
                登录
              </Button>
            ))}
          </div>
        </div>
      </header>

      {/* Entry cards */}
      <main className="wj-main max-w-screen-md mx-auto px-4 py-6 space-y-4">
        <p className="wj-kicker text-sm text-[#64748B] mb-2">请选择你的需求，开始志愿分析</p>

        <EntryCard
          icon={Compass}
          title="我还没思路"
          description="刚出分，帮你生成三套方案"
          materials="省份 + 分数/位次 + 选科"
          estimatedTime="约 15 分钟"
          actionLabel="开始分析"
          href="/assess"
        />

        <EntryCard
          icon={ClipboardCheck}
          title="我已有志愿表"
          description="帮你检查风险和盲区"
          materials="已填好的志愿草稿"
          estimatedTime="约 5 分钟"
          actionLabel="上传志愿表"
          href="/volunteer-check"
        />

        <EntryCard
          icon={BarChart2}
          title="我想比较学校/专业"
          description="Phase 2，即将推出"
          materials="—"
          estimatedTime="—"
          actionLabel="即将推出"
          disabled
          disabledReason="功能开发中，敬请期待"
        />
      </main>

      <LoginSheet
        isOpen={loginOpen}
        onClose={() => setLoginOpen(false)}
      />

      <DebugDrawer />
    </div>
  )
}
