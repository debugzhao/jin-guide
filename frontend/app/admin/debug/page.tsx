'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import DebugConsole from '@/components/admin/debug/DebugConsole'

type AccessState = 'checking' | 'allowed' | 'denied'

// 独立鉴权路由：仅 role=admin 可访问，其他访客（含未登录）看到 403 提示。
// 之前的实现是首页任意访客可开的 Drawer，这里对齐 PRD §6.9 的角色校验要求。
export default function AdminDebugPage() {
  const [access, setAccess] = useState<AccessState>('checking')
  const router = useRouter()

  useEffect(() => {
    api
      .me()
      .then((user) => setAccess(user.role === 'admin' ? 'allowed' : 'denied'))
      .catch(() => setAccess('denied'))
  }, [])

  if (access === 'checking') {
    return (
      <div className="fixed inset-0 bg-white flex items-center justify-center">
        <p className="text-sm text-gray-500">正在校验权限…</p>
      </div>
    )
  }

  if (access === 'denied') {
    return (
      <div className="fixed inset-0 bg-white flex flex-col items-center justify-center gap-3 text-center px-6">
        <h1 className="text-lg font-semibold text-gray-900">403 无权访问</h1>
        <p className="text-sm text-gray-500">Admin Debug 控制台仅限管理员访问</p>
        <button onClick={() => router.push('/')} className="text-sm text-blue-600 underline">
          返回首页
        </button>
      </div>
    )
  }

  return <DebugConsole />
}
