'use client'

import { useEffect, useRef } from 'react'
import { X, AlertCircle, RefreshCw } from 'lucide-react'
import { useAppStore } from '@/lib/store'
import { chatApi } from '@/lib/api'
import ChatMessageBubble, { ChatStreamingBubble } from './ChatMessageBubble'
import ChatSuggestedQuestions from './ChatSuggestedQuestions'
import ChatInput from './ChatInput'
import type { ChatMessage } from '@/types'

interface Props {
  reportId: string
}

export default function ChatPanel({ reportId }: Props) {
  const {
    isChatPanelOpen,
    closeChatPanel,
    messages,
    setChatMessages,
    streamingContent,
    isStreaming,
    dailyLimitReached,
    appendUserMessage,
    appendStreamToken,
    commitStreamingMessage,
    setDailyLimitReached,
  } = useAppStore()

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<(() => void) | null>(null)

  // Load history when panel opens
  useEffect(() => {
    if (!isChatPanelOpen || !reportId) return
    chatApi
      .getHistory(reportId)
      .then((res) => {
        const mapped: ChatMessage[] = res.messages.map((m, i) => ({
          id: `hist-${i}`,
          role: m.role,
          content: m.content,
          citations: m.citations ?? [],
          created_at: m.created_at,
        }))
        setChatMessages(mapped)
      })
      .catch(() => {}) // silently ignore — panel still usable
  }, [isChatPanelOpen, reportId, setChatMessages])

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  // Clean up SSE on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.()
    }
  }, [])

  const handleSend = (message: string) => {
    if (isStreaming) return
    appendUserMessage(message)

    const abort = chatApi.streamMessage(reportId, message, {
      onToken: (token) => appendStreamToken(token),
      onCitation: () => {},
      onDone: (citations) => commitStreamingMessage(citations),
      onComplianceWarning: () => {},
      onError: (msg) => {
        commitStreamingMessage()
        console.error('Chat error:', msg)
      },
      onRateLimit: () => {
        setDailyLimitReached(true)
        commitStreamingMessage()
      },
    })
    abortRef.current = abort
  }

  if (!isChatPanelOpen) return null

  return (
    <>
      {/* Mobile: Bottom Sheet overlay */}
      <div
        className="fixed inset-0 bg-black/30 z-40 md:hidden"
        onClick={closeChatPanel}
      />

      {/* Panel — Bottom Sheet on mobile, Right Drawer on desktop */}
      <div
        className="
          fixed z-50 bg-white flex flex-col shadow-xl
          /* mobile: bottom sheet */
          bottom-0 left-0 right-0 rounded-t-2xl h-[70vh]
          /* desktop: right drawer */
          md:top-0 md:right-0 md:bottom-0 md:left-auto md:w-[380px] md:h-full md:rounded-none md:border-l md:border-gray-200
        "
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 flex-shrink-0">
          <div>
            <p className="text-sm font-semibold text-gray-900">问问 AI 助手</p>
            <p className="text-[10px] text-gray-400">基于你的志愿报告解答问题</p>
          </div>
          <button
            onClick={closeChatPanel}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            aria-label="关闭"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {messages.length === 0 && !isStreaming ? (
            <ChatSuggestedQuestions onSelect={handleSend} />
          ) : (
            <>
              {messages.map((msg) => (
                <ChatMessageBubble key={msg.id} message={msg} />
              ))}
              {isStreaming && (
                <ChatStreamingBubble content={streamingContent} />
              )}
            </>
          )}

          {dailyLimitReached && (
            <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-amber-50 border border-amber-200">
              <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0" />
              <p className="text-xs text-amber-700">今日问答次数已达上限，明日 0 点重置</p>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        {!dailyLimitReached && (
          <ChatInput onSend={handleSend} disabled={isStreaming} />
        )}

        {/* Disclaimer */}
        <div className="px-4 pb-safe-bottom pb-2 flex-shrink-0">
          <p className="text-[10px] text-gray-400 text-center">
            AI 回复仅供参考，不构成录取承诺
          </p>
        </div>
      </div>
    </>
  )
}
