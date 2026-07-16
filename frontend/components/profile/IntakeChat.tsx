'use client'

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, RefreshCw, Sparkles } from 'lucide-react'
import ChatInput from '@/components/chat/ChatInput'
import ChatMessageBubble, { ChatStreamingBubble } from '@/components/chat/ChatMessageBubble'
import { api, intakeChatApi } from '@/lib/api'
import { useAppStore } from '@/lib/store'
import type { ChatMessage } from '@/types'

interface IntakeChatProps {
  /** IntakeAgent 调用 start_profile_capture 工具时回调，父组件据此切到 profile 阶段 */
  onStartProfile: () => void
  /** 建档阶段开始后锁定：只保留历史文案，收起欢迎态和输入框，避免和建档表单同时出现两个输入入口 */
  locked: boolean
}

const SUGGESTED_PROMPTS = ['开始志愿建档', '浙江大学在河南大概多少分', '对比一下浙大和南大在河南的选科要求']

let seq = 0
const nextId = () => `intake-${(seq += 1)}`

const toMessage = (role: ChatMessage['role'], content: string): ChatMessage => ({
  id: nextId(),
  role,
  content,
  citations: [],
  created_at: new Date().toISOString(),
})

/**
 * Chat-first 首屏入口 (docs/frontend-prd-v2.md §Chat-first 建档入口)：一个真正的
 * 多轮流式 chatbot，话题限定在高考志愿相关范围（查学校/查分数/查专业/对比学校/
 * 引导建档），由 IntakeAgent 通过 function calling 决定何时调用确定性查询工具、
 * 何时调用 start_profile_capture 触发建档表单——不再是旧版"先分类再二选一"。
 */
export default function IntakeChat({ onStartProfile, locked }: IntakeChatProps) {
  const currentIntakeConversationId = useAppStore((s) => s.currentIntakeConversationId)
  const setCurrentIntakeConversationId = useAppStore((s) => s.setCurrentIntakeConversationId)
  const bumpConversationListVersion = useAppStore((s) => s.bumpConversationListVersion)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [dailyLimitReached, setDailyLimitReached] = useState(false)
  const [dailyLimitMessage, setDailyLimitMessage] = useState<string | undefined>()
  const [lastFailedMessage, setLastFailedMessage] = useState<string | null>(null)

  const streamBufferRef = useRef('')
  const abortRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    let cancelled = false

    const bootstrap = async () => {
      try {
        await api.createAnonymousSession()
      } catch {
        // best-effort：拿不到匿名会话时聊天仍可用，只是历史不会持久化
      }
      // 没有 conversation_id = 全新对话，不拉历史，直接展示欢迎态
      // （父组件在切换/新建会话时会用 key 强制重新挂载本组件，见 app/page.tsx）
      if (!currentIntakeConversationId) return
      try {
        const res = await intakeChatApi.getHistory(currentIntakeConversationId)
        if (!cancelled && res.messages.length > 0) {
          setMessages(res.messages.map((m) => toMessage(m.role, m.content)))
        }
      } catch {
        // ignore — 从空历史开始
      }
    }

    bootstrap()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    return () => {
      abortRef.current?.()
    }
  }, [])

  const handleSend = (text: string) => {
    if (isStreaming) return
    setLastFailedMessage(null)
    setMessages((prev) => [...prev, toMessage('user', text)])
    setIsStreaming(true)
    setStreamingContent('')
    streamBufferRef.current = ''

    const abort = intakeChatApi.streamMessage(text, currentIntakeConversationId, {
      onToken: (token) => {
        streamBufferRef.current += token
        setStreamingContent(streamBufferRef.current)
      },
      onTriggerProfileCapture: () => onStartProfile(),
      onDone: (conversationId) => {
        if (streamBufferRef.current) {
          setMessages((prev) => [...prev, toMessage('assistant', streamBufferRef.current)])
        }
        setStreamingContent('')
        setIsStreaming(false)
        if (conversationId && conversationId !== currentIntakeConversationId) {
          setCurrentIntakeConversationId(conversationId)
        }
        bumpConversationListVersion()
      },
      onComplianceWarning: () => {},
      onError: (msg) => {
        setStreamingContent('')
        setIsStreaming(false)
        setLastFailedMessage(text)
        console.error('Intake chat error:', msg)
      },
      onRateLimit: (msg) => {
        setDailyLimitReached(true)
        setDailyLimitMessage(msg)
        setStreamingContent('')
        setIsStreaming(false)
      },
    })
    abortRef.current = abort
  }

  const handleRetry = () => {
    if (!lastFailedMessage) return
    const msg = lastFailedMessage
    setLastFailedMessage(null)
    handleSend(msg)
  }

  const handlePromptClick = (prompt: string) => {
    if (prompt === '开始志愿建档') {
      onStartProfile()
      return
    }
    handleSend(prompt)
  }

  const messageList = (
    <div className="space-y-3">
      {messages.map((msg) => (
        <ChatMessageBubble key={msg.id} message={msg} />
      ))}
      {isStreaming && <ChatStreamingBubble content={streamingContent} />}

      {lastFailedMessage && !isStreaming && (
        <div className="flex items-center justify-between gap-2 px-3 py-2.5 rounded-btn bg-[#FEF2F2] border border-[#FECACA]">
          <p className="text-xs text-[#DC2626]">连接中断，消息未发送成功</p>
          <button onClick={handleRetry} className="flex items-center gap-1 text-xs text-[#DC2626] font-medium flex-shrink-0">
            <RefreshCw className="w-3 h-3" />
            重试
          </button>
        </div>
      )}

      {dailyLimitReached && (
        <div className="flex items-center gap-2 px-3 py-2.5 rounded-btn bg-[#FFFBEB] border border-[#FDE68A]">
          <AlertCircle className="w-4 h-4 text-[#D97706] flex-shrink-0" />
          <p className="text-xs text-[#D97706]">{dailyLimitMessage || '今日对话次数已达上限，明日 0 点重置'}</p>
        </div>
      )}
    </div>
  )

  if (locked) {
    if (messages.length === 0) return null
    return messageList
  }

  if (messages.length === 0 && !isStreaming) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-5">
        <div className="w-12 h-12 rounded-full bg-gradient-to-br from-[#1E40AF] to-[#2563EB] flex items-center justify-center">
          <Sparkles className="w-6 h-6 text-white" />
        </div>
        <div className="text-center space-y-1">
          <p className="text-base font-semibold text-[#0F172A]">你好，我是问津</p>
          <p className="text-sm text-[#64748B]">查学校、查分数、对比院校，或直接开始志愿建档</p>
        </div>

        <div className="w-full grid grid-cols-1 gap-2">
          {SUGGESTED_PROMPTS.map((p) => (
            <button
              key={p}
              onClick={() => handlePromptClick(p)}
              className="w-full text-left px-3.5 py-2.5 rounded-xl wj-glass-card
                hover:border-[#1E40AF]/30 text-sm text-[#64748B] hover:text-[#0F172A] transition-colors"
            >
              {p}
            </button>
          ))}
        </div>

        <div className="w-full">
          {!dailyLimitReached && (
            <ChatInput onSend={handleSend} disabled={isStreaming} placeholder="输入你的问题，或直接说想开始建档…" />
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col">
      <div className="pb-3 space-y-3">
        {messageList}
        {!isStreaming && (
          <button onClick={() => onStartProfile()} className="text-xs text-[#1E40AF] hover:underline">
            直接开始志愿建档 →
          </button>
        )}
      </div>

      <div className="mt-auto sticky bottom-0 bg-white pt-1 pb-6">
        {!dailyLimitReached && (
          <ChatInput onSend={handleSend} disabled={isStreaming} placeholder="继续聊聊，或直接开始建档…" />
        )}
      </div>
    </div>
  )
}
