'use client'

import { useEffect, useRef, useState } from 'react'
import { X, AlertCircle, RefreshCw, Trash2 } from 'lucide-react'
import { useAppStore } from '@/lib/store'
import { chatApi } from '@/lib/api'
import ChatMessageBubble, { ChatStreamingBubble } from './ChatMessageBubble'
import ChatSuggestedQuestions from './ChatSuggestedQuestions'
import ChatInput from './ChatInput'
import type { ChatMessage } from '@/types'

const HISTORY_WARNING_THRESHOLD = 40

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
    dailyLimitMessage,
    lastFailedMessage,
    appendUserMessage,
    appendStreamToken,
    commitStreamingMessage,
    setDailyLimitReached,
    setLastFailedMessage,
    clearChat,
  } = useAppStore()

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<(() => void) | null>(null)
  const [confirmingClear, setConfirmingClear] = useState(false)

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
    setLastFailedMessage(null)
    appendUserMessage(message)

    const abort = chatApi.streamMessage(reportId, message, {
      onToken: (token) => appendStreamToken(token),
      onCitation: () => {},
      onDone: (citations) => commitStreamingMessage(citations),
      onComplianceWarning: () => {},
      onError: (msg) => {
        commitStreamingMessage()
        setLastFailedMessage(message)
        console.error('Chat error:', msg)
      },
      onRateLimit: (msg) => {
        setDailyLimitReached(true, msg)
        commitStreamingMessage()
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

  const handleClearChat = async () => {
    if (!confirmingClear) {
      setConfirmingClear(true)
      return
    }
    setConfirmingClear(false)
    try {
      await chatApi.clearHistory(reportId)
    } catch {
      // best-effort — clear local state regardless so the UI doesn't feel stuck
    }
    clearChat()
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
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              confirmingClear ? (
                <div className="flex items-center gap-1.5 mr-1">
                  <span className="text-[11px] text-gray-500">确定清除？</span>
                  <button
                    onClick={() => setConfirmingClear(false)}
                    className="text-[11px] text-gray-400 hover:text-gray-600 px-1"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleClearChat}
                    className="text-[11px] text-red-600 hover:text-red-700 font-medium px-1"
                  >
                    确定
                  </button>
                </div>
              ) : (
                <button
                  onClick={handleClearChat}
                  className="flex items-center gap-1 px-1.5 py-1 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                  aria-label="清除对话"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span className="text-[11px]">清除对话</span>
                </button>
              )
            )}
            <button
              onClick={closeChatPanel}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              aria-label="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {messages.length === 0 && !isStreaming ? (
            <ChatSuggestedQuestions onSelect={handleSend} />
          ) : (
            <>
              {messages.length > HISTORY_WARNING_THRESHOLD && (
                <p className="text-center text-[11px] text-gray-400 py-1">
                  对话已超过 {HISTORY_WARNING_THRESHOLD} 条，较早的内容可能影响回答的连贯性
                </p>
              )}
              {messages.map((msg) => (
                <ChatMessageBubble key={msg.id} message={msg} />
              ))}
              {isStreaming && (
                <ChatStreamingBubble content={streamingContent} />
              )}
            </>
          )}

          {lastFailedMessage && !isStreaming && (
            <div className="flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl bg-red-50 border border-red-200">
              <p className="text-xs text-red-700">连接中断，消息未发送成功</p>
              <button
                onClick={handleRetry}
                className="flex items-center gap-1 text-xs text-red-700 font-medium hover:text-red-800 flex-shrink-0"
              >
                <RefreshCw className="w-3 h-3" />
                重试
              </button>
            </div>
          )}

          {dailyLimitReached && (
            <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-amber-50 border border-amber-200">
              <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0" />
              <p className="text-xs text-amber-700">
                {dailyLimitMessage || '今日问答次数已达上限，明日 0 点重置'}
              </p>
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
