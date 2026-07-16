'use client'

import { useEffect, useState } from 'react'
import { MessageSquare, Plus } from 'lucide-react'
import Button from '@/components/ui/Button'
import UserMenu from '@/components/ui/UserMenu'
import { intakeChatApi, type IntakeConversationListItem } from '@/lib/api'
import { useAppStore } from '@/lib/store'

interface SidebarNavProps {
  onNewConversation: () => void
  /** 点击某条历史会话——切到该会话并继续对话，见 app/page.tsx handleSelectConversation */
  onSelectConversation: (conversationId: string) => void
  onLoginClick: () => void
}

/** 左侧持久导航栏（对齐千问式布局）：新建对话 + 建档前聊天的历史会话列表。 */
export default function SidebarNav({ onNewConversation, onSelectConversation, onLoginClick }: SidebarNavProps) {
  const { user, authChecked, currentIntakeConversationId, conversationListVersion } = useAppStore()
  const [conversations, setConversations] = useState<IntakeConversationListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    intakeChatApi
      .listConversations()
      .then((res) => {
        if (cancelled) return
        setConversations(res.items)
        setNextCursor(res.next_cursor)
        setHasMore(res.has_more)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [conversationListVersion])

  const loadMore = () => {
    if (!nextCursor) return
    intakeChatApi
      .listConversations(nextCursor)
      .then((res) => {
        setConversations((prev) => [...prev, ...res.items])
        setNextCursor(res.next_cursor)
        setHasMore(res.has_more)
      })
      .catch(() => {})
  }

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

      <div className="flex-1 overflow-y-auto px-3 py-4 space-y-0.5">
        {loading ? (
          <p className="text-[11px] text-[#94A3B8] px-1">加载中…</p>
        ) : conversations.length === 0 ? (
          <p className="text-[11px] text-[#94A3B8] px-1">暂无历史对话</p>
        ) : (
          <>
            {conversations.map((c) => (
              <button
                key={c.id}
                onClick={() => onSelectConversation(c.id)}
                className={`w-full flex items-center gap-2 px-2 py-2 rounded-lg text-left text-[13px] transition-colors ${
                  c.id === currentIntakeConversationId
                    ? 'bg-[#EFF6FF] text-[#1E40AF]'
                    : 'text-[#334155] hover:bg-[#F8FAFC]'
                }`}
              >
                <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
                <span className="truncate">{c.title || '新对话'}</span>
              </button>
            ))}
            {hasMore && (
              <button
                onClick={loadMore}
                className="w-full text-center text-[11px] text-[#64748B] hover:text-[#0F172A] px-2 py-2"
              >
                加载更多
              </button>
            )}
          </>
        )}
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
