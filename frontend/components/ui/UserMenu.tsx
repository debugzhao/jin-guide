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
      // best-effort — clear local state regardless so the UI doesn't feel stuck
    }
    clearUser()
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
        <div className="absolute right-0 top-full mt-2 w-56 rounded-xl border border-[#E2E8F0] bg-white shadow-lg z-50 overflow-hidden">
          <div className="px-4 py-3 border-b border-[#E2E8F0]">
            <p className="text-sm text-[#0F172A] truncate">{user.email}</p>
            {user.role === 'admin' && (
              <span className="inline-block mt-1 text-[10px] font-medium text-[#1E40AF] bg-[#EFF6FF] px-1.5 py-0.5 rounded">
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
