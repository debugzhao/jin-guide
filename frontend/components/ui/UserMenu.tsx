'use client'

import { useEffect, useRef, useState } from 'react'
import { LogOut } from 'lucide-react'
import { api } from '@/lib/api'
import { useAppStore } from '@/lib/store'

export default function UserMenu() {
  const user = useAppStore((s) => s.user)
  const clearUser = useAppStore((s) => s.clearUser)
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  if (!user) return null

  const initial = user.email.charAt(0).toUpperCase()

  const handleLogout = async () => {
    setOpen(false)
    try {
      await api.logout()
    } catch {
      // 尽力而为——无论如何都清空本地状态，避免 UI 卡住的感觉
    }
    clearUser()
    // 清掉建档前聊天/报告问答缓存的消息和当前会话 id，避免退出登录后浏览器
    // 上还残留着刚才那个账号的对话内容（见 store.ts resetOnLogout 的说明）。
    useAppStore.getState().resetOnLogout()
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-8 h-8 rounded-full bg-[#1E40AF] text-white text-sm font-semibold flex items-center justify-center hover:opacity-90 transition-opacity"
        aria-label="账号菜单"
      >
        {initial}
      </button>

      {open && (
        // 这个组件目前只用在 SidebarNav 侧栏底部（左下角）——按钮紧贴侧栏左边缘和
        // 底部，侧栏外层容器又是 overflow-hidden（WorkspaceShell.tsx），如果像
        // 一般下拉菜单那样向下、右对齐展开（top-full + right-0，对齐的是这个只有
        // 32px 宽的按钮本身），菜单会同时越过视口底部和侧栏左边缘被裁掉，点击
        // 按钮时看起来毫无反应。向上、左对齐展开才能完整落在侧栏可见区域内。
        <div className="absolute left-0 bottom-full mb-2 w-56 rounded-card border border-[#E2E8F0] bg-white shadow-floating z-50 overflow-hidden">
          <div className="px-4 py-3 border-b border-[#E2E8F0]">
            <p className="text-sm text-[#0F172A] truncate">{user.email}</p>
            {user.role === 'admin' && (
              <span className="inline-block mt-1 text-micro font-medium text-[#1E40AF] bg-[#EFF6FF] px-1.5 py-0.5 rounded">
                管理员
              </span>
            )}
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-[#DC2626] hover:bg-[#FEF2F2] transition-colors"
          >
            <LogOut className="w-4 h-4" />
            退出登录
          </button>
        </div>
      )}
    </div>
  )
}
