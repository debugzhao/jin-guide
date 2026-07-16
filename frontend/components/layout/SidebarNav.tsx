'use client'

import { useEffect, useRef, useState } from 'react'
import { MessageSquare, MoreHorizontal, PanelLeftClose, Pencil, Plus, Trash2 } from 'lucide-react'
import Button from '@/components/ui/Button'
import Modal from '@/components/ui/Modal'
import UserMenu from '@/components/ui/UserMenu'
import { intakeChatApi, type IntakeConversationListItem } from '@/lib/api'
import { useAppStore } from '@/lib/store'

interface SidebarNavProps {
  onNewConversation: () => void
  /** 点击某条历史会话——切到该会话并继续对话，见 app/page.tsx handleSelectConversation */
  onSelectConversation: (conversationId: string) => void
  onLoginClick: () => void
  /** 桌面端收起整个侧栏；不传则不渲染收起按钮（移动端抽屉场景用不到） */
  onToggleSidebar?: () => void
}

interface ConversationRowProps {
  conversation: IntakeConversationListItem
  active: boolean
  onSelect: () => void
  onRename: (title: string) => void
  onRequestDelete: () => void
}

/** 单条历史会话：默认态可点选；"⋯" 打开重命名/删除菜单；重命名态原地切成输入框。 */
function ConversationRow({ conversation, active, onSelect, onRename, onRequestDelete }: ConversationRowProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(conversation.title || '')
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [menuOpen])

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const startEditing = () => {
    setDraft(conversation.title || '')
    setEditing(true)
    setMenuOpen(false)
  }

  const commitEditing = () => {
    const trimmed = draft.trim()
    setEditing(false)
    if (trimmed && trimmed !== conversation.title) onRename(trimmed)
  }

  if (editing) {
    return (
      <div ref={rootRef} className="px-2 py-1">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitEditing}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitEditing()
            if (e.key === 'Escape') setEditing(false)
          }}
          maxLength={50}
          className="w-full text-[13px] px-1.5 py-1 rounded border border-[#1E40AF]/40 outline-none"
        />
      </div>
    )
  }

  return (
    <div ref={rootRef} className="relative group">
      <button
        onClick={onSelect}
        className={`w-full flex items-center gap-2 px-2 py-2 pr-7 rounded-lg text-left text-[13px] transition-colors ${
          active ? 'bg-[#EFF6FF] text-[#1E40AF]' : 'text-[#334155] hover:bg-[#F8FAFC]'
        }`}
      >
        <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
        <span className="truncate">{conversation.title || '新对话'}</span>
      </button>

      <button
        onClick={(e) => {
          e.stopPropagation()
          setMenuOpen((v) => !v)
        }}
        aria-label="会话操作"
        className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded text-[#94A3B8] opacity-0 group-hover:opacity-100 hover:bg-[#E2E8F0] hover:text-[#0F172A] transition-opacity"
      >
        <MoreHorizontal className="w-3.5 h-3.5" />
      </button>

      {menuOpen && (
        <div className="absolute right-1 top-full mt-1 w-32 rounded-lg border border-[#E2E8F0] bg-white shadow-lg z-50 overflow-hidden">
          <button
            onClick={startEditing}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[#334155] hover:bg-[#F8FAFC]"
          >
            <Pencil className="w-3.5 h-3.5" />
            重命名
          </button>
          <button
            onClick={() => {
              setMenuOpen(false)
              onRequestDelete()
            }}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[#DC2626] hover:bg-[#FEF2F2]"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        </div>
      )}
    </div>
  )
}

/** 左侧持久导航栏（对齐千问式布局）：新建对话 + 建档前聊天的历史会话列表（可重命名/删除）。 */
export default function SidebarNav({ onNewConversation, onSelectConversation, onLoginClick, onToggleSidebar }: SidebarNavProps) {
  const { user, authChecked, currentIntakeConversationId, conversationListVersion } = useAppStore()
  const [conversations, setConversations] = useState<IntakeConversationListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<IntakeConversationListItem | null>(null)

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

  const handleRename = (conversationId: string, title: string) => {
    setConversations((prev) => prev.map((c) => (c.id === conversationId ? { ...c, title } : c)))
    intakeChatApi.renameConversation(conversationId, title).catch(() => {
      // 失败也不强行回滚本地文案——重命名是低风险操作，下次拉列表会用服务端真值覆盖
    })
  }

  const handleConfirmDelete = async () => {
    if (!pendingDelete) return
    const { id } = pendingDelete
    setPendingDelete(null)
    setConversations((prev) => prev.filter((c) => c.id !== id))
    try {
      await intakeChatApi.deleteConversation(id)
    } catch {
      // best-effort：本地已经移除，下次刷新列表会自我修正
    }
    if (id === currentIntakeConversationId) onNewConversation()
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-4 flex-shrink-0 flex items-start justify-between gap-2">
        <div>
          <h1 className="text-base font-bold text-[#0F172A]">
            问津 <span className="text-[#1E40AF]">Agent</span>
          </h1>
          <p className="text-[11px] text-[#64748B] mt-0.5">AI 志愿决策助理</p>
        </div>
        {onToggleSidebar && (
          <button
            onClick={onToggleSidebar}
            aria-label="收起侧栏"
            className="hidden lg:inline-flex p-1.5 -mr-1 rounded-btn text-[#94A3B8] hover:text-[#0F172A] hover:bg-[#F1F5F9] transition-colors flex-shrink-0"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        )}
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
              <ConversationRow
                key={c.id}
                conversation={c}
                active={c.id === currentIntakeConversationId}
                onSelect={() => onSelectConversation(c.id)}
                onRename={(title) => handleRename(c.id, title)}
                onRequestDelete={() => setPendingDelete(c)}
              />
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

      <Modal isOpen={!!pendingDelete} onClose={() => setPendingDelete(null)} title="删除该会话？">
        <p className="text-sm text-[#64748B] mb-5">
          「{pendingDelete?.title || '新对话'}」将从历史记录中移除，此操作不可恢复。
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setPendingDelete(null)}>
            取消
          </Button>
          <Button
            size="sm"
            className="bg-[#DC2626] hover:bg-[#B91C1C]"
            onClick={handleConfirmDelete}
          >
            删除
          </Button>
        </div>
      </Modal>
    </div>
  )
}
