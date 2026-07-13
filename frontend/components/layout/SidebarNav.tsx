'use client'

import { Plus } from 'lucide-react'
import Button from '@/components/ui/Button'
import UserMenu from '@/components/ui/UserMenu'
import { useAppStore } from '@/lib/store'

interface SidebarNavProps {
  onNewConversation: () => void
  onLoginClick: () => void
}

/**
 * 左侧持久导航栏（对齐千问式布局）。本轮只做骨架占位——历史对话列表接入
 * 真实数据、点击切换会话是下一轮范围，这里先用静态占位文案，避免布局
 * 落地后又要为空态/加载态单独返工。
 */
export default function SidebarNav({ onNewConversation, onLoginClick }: SidebarNavProps) {
  const { user, authChecked } = useAppStore()

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-4 flex-shrink-0">
        <h1 className="text-base font-bold text-[#0F172A]">
          问津 <span className="text-[#1E40AF]">Agent</span>
        </h1>
        <p className="text-[11px] text-[#64748B] mt-0.5">AI 志愿决策助理</p>
      </div>

      <div className="px-3 flex-shrink-0">
        <Button variant="outline" size="sm" className="w-full justify-start gap-1.5" onClick={onNewConversation}>
          <Plus className="w-3.5 h-3.5" />
          新建对话
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-4">
        <p className="text-[11px] text-[#94A3B8] px-1">历史记录即将上线</p>
      </div>

      <div className="px-3 py-3 border-t border-[#E2E8F0] flex-shrink-0">
        {authChecked && (
          user ? (
            <div className="flex items-center gap-2">
              <UserMenu />
              <span className="text-xs text-[#64748B] truncate">{user.email}</span>
            </div>
          ) : (
            <Button variant="ghost" size="sm" className="w-full" onClick={onLoginClick}>
              登录
            </Button>
          )
        )}
      </div>
    </div>
  )
}
