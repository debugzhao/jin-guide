'use client'

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, RefreshCw, Trash2 } from 'lucide-react'
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

/**
 * 报告问答对话列——报告工作台左侧持续对话栏的常驻内容（F2/F6 的前置形态）。
 * 取代旧版 `ChatPanel` 的固定定位抽屉/bottom sheet 呈现，改为嵌入
 * `WorkspaceShell` 左栏的普通流式布局，桌面端常驻可见，不需要开关。
 */
export default function ChatColumn({ reportId }: Props) {
  const {
    messages,
    setChatMessages,
    streamingContent,
    isStreaming,
    dailyLimitReached,
    dailyLimitMessage,
    lastFailedMessage,
    setActiveReport,
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

  useEffect(() => {
    setActiveReport(reportId)
  }, [reportId, setActiveReport])

  useEffect(() => {
    if (!reportId) return
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
  }, [reportId, setChatMessages])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

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

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between pb-3 border-b border-white/10">
        <div>
          <p className="text-sm font-semibold text-[#F1F5F9]">问津助手</p>
          <p className="text-[10px] text-[#6B7280]">基于你的志愿报告解答问题</p>
        </div>
        {messages.length > 0 && (
          confirmingClear ? (
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-[#9CA3C4]">确定清除？</span>
              <button onClick={() => setConfirmingClear(false)} className="text-[11px] text-[#6B7280] hover:text-[#9CA3C4] px-1">
                取消
              </button>
              <button onClick={handleClearChat} className="text-[11px] text-[#F2A9A9] hover:opacity-80 font-medium px-1">
                确定
              </button>
            </div>
          ) : (
            <button
              onClick={handleClearChat}
              className="flex items-center gap-1 px-1.5 py-1 rounded-btn text-[#6B7280] hover:text-[#F2A9A9] transition-colors"
              aria-label="清除对话"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span className="text-[11px]">清除对话</span>
            </button>
          )
        )}
      </div>

      <div className="py-3 space-y-3">
        {messages.length === 0 && !isStreaming ? (
          <ChatSuggestedQuestions onSelect={handleSend} />
        ) : (
          <>
            {messages.length > HISTORY_WARNING_THRESHOLD && (
              <p className="text-center text-[11px] text-[#6B7280] py-1">
                对话较长，建议清除后重新提问以保持上下文准确
              </p>
            )}
            {messages.map((msg) => (
              <ChatMessageBubble key={msg.id} message={msg} />
            ))}
            {isStreaming && <ChatStreamingBubble content={streamingContent} />}
          </>
        )}

        {lastFailedMessage && !isStreaming && (
          <div className="flex items-center justify-between gap-2 px-3 py-2.5 rounded-btn bg-[rgba(242,169,169,0.12)] border border-[rgba(242,169,169,0.32)]">
            <p className="text-xs text-[#F2A9A9]">连接中断，消息未发送成功</p>
            <button onClick={handleRetry} className="flex items-center gap-1 text-xs text-[#F2A9A9] font-medium flex-shrink-0">
              <RefreshCw className="w-3 h-3" />
              重试
            </button>
          </div>
        )}

        {dailyLimitReached && (
          <div className="flex items-center gap-2 px-3 py-2.5 rounded-btn bg-[rgba(239,196,138,0.12)] border border-[rgba(239,196,138,0.32)]">
            <AlertCircle className="w-4 h-4 text-[#EFC48A] flex-shrink-0" />
            <p className="text-xs text-[#EFC48A]">
              {dailyLimitMessage || '今日问答次数已达上限，明日 0 点重置'}
            </p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {!dailyLimitReached && <ChatInput onSend={handleSend} disabled={isStreaming} />}

      <p className="text-[10px] text-[#6B7280] text-center pt-2 flex-shrink-0">
        以上分析基于报告数据，最终填报请以省级考试院为准
      </p>
    </div>
  )
}
