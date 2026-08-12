'use client'

import { useEffect } from 'react'
import { AlertCircle, RefreshCw, Sparkles } from 'lucide-react'
import ChatInput from '@/components/chat/ChatInput'
import ChatMessageBubble, { ChatStreamingBubble } from '@/components/chat/ChatMessageBubble'
import { api, intakeChatApi } from '@/lib/api'
import {
  useAppStore,
  EMPTY_INTAKE_CONVERSATION_STATE,
  INTAKE_DRAFT_KEY,
  setIntakeAbort,
} from '@/lib/store'
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
 *
 * 消息/流式状态存在 Zustand `intakeConversations[key]`（见 lib/store.ts），不是组件
 * 本地 state：侧栏切换会话时 app/page.tsx 会用 `conversationKey` 强制重新挂载本组件，
 * 如果状态是本地的，正在流式生成的内容和已经等到的历史都会随组件销毁而丢失
 * （2026-07-27 的两个真实 bug）。状态挪到 store 后，重新挂载的新实例读到的还是
 * 同一份数据，且请求本身也不再随组件卸载被 abort。
 */
export default function IntakeChat({ onStartProfile, locked }: IntakeChatProps) {
  const currentIntakeConversationId = useAppStore((s) => s.currentIntakeConversationId)
  const setCurrentIntakeConversationId = useAppStore((s) => s.setCurrentIntakeConversationId)
  const bumpConversationListVersion = useAppStore((s) => s.bumpConversationListVersion)
  const key = currentIntakeConversationId ?? INTAKE_DRAFT_KEY

  const conv = useAppStore((s) => s.intakeConversations[key] ?? EMPTY_INTAKE_CONVERSATION_STATE)
  const {
    messages,
    streamingContent,
    isStreaming,
    dailyLimitReached,
    dailyLimitMessage,
    lastFailedMessage,
  } = conv

  useEffect(() => {
    let cancelled = false

    const bootstrap = async () => {
      try {
        await api.createAnonymousSession()
      } catch {
        // best-effort：拿不到匿名会话时聊天仍可用，只是历史不会持久化
      }

      // 已经有这个 key 的数据（正在流式生成、已经拉过历史、或者本地已经有消息），
      // 不重复拉取——这正是修复"切回某个会话时不应该覆盖掉已经在跑的内容"的关键。
      const existing = useAppStore.getState().intakeConversations[key]
      if (existing?.historyLoaded || existing?.isStreaming || (existing?.messages.length ?? 0) > 0) {
        return
      }

      if (key === INTAKE_DRAFT_KEY) {
        // 全新对话，后端还没有这个会话，不用发请求
        useAppStore.getState().setIntakeHistoryLoaded(key, [])
        return
      }

      try {
        const res = await intakeChatApi.getHistory(key)
        if (!cancelled) {
          useAppStore.getState().setIntakeHistoryLoaded(key, res.messages.map((m) => toMessage(m.role, m.content)))
        }
      } catch (err) {
        // 404 = 持久化到 localStorage 的 conversation_id 与当前 cookie 身份对不上
        // （孤儿 id：匿名会话轮换/登出后残留）。清掉它回落到全新会话，否则用户会停在
        // 一个空白且一发消息就 404 的死会话上。其它错误按老逻辑降级成空历史。
        if (!cancelled && (err as { status?: number })?.status === 404) {
          if (useAppStore.getState().currentIntakeConversationId === key) {
            setCurrentIntakeConversationId(null)
          }
        } else if (!cancelled) {
          useAppStore.getState().setIntakeHistoryLoaded(key, [])
        }
      }
    }

    bootstrap()
    return () => {
      cancelled = true
    }
  }, [key])

  const handleSend = (text: string) => {
    const store = useAppStore.getState()
    if (store.intakeConversations[key]?.isStreaming) return
    store.intakeSetLastFailedMessage(key, null)
    store.intakeAppendUserMessage(key, text)

    // 打字机效果：SSE 到达的文本不是逐字符的（工具查询类回复现在整段一次性到达，
    // 见 backend/app/agent/intake_agent.py::_format_tool_result_text），如果直接
    // 原样吐给 store，长的一段话会一次性"跳"出来，看起来一顿一顿的。这里把所有
    // 到达的文本先塞进一个队列，用 requestAnimationFrame 循环按小份匀速吐出去，
    // 显示进度和网络到达进度解耦——网络快就让队列攒着，显示始终是平滑的逐字符
    // 效果；网络已经把整段答案发完时，用"队列越长吐得越快"的自适应速率追上，
    // 避免长回答被硬吐字拖出好几秒延迟（这正好会抵消刚做完的性能优化）。
    const BASE_CHARS_PER_FRAME = 2
    const CATCHUP_DIVISOR = 12

    let contentQueue = ''
    let revealHandle: number | null = null
    let pendingDone: { conversationId?: string } | null = null

    const finalizeDone = () => {
      useAppStore.getState().intakeCommitStreamingMessage(key)
      setIntakeAbort(key, null)
      const conversationId = pendingDone?.conversationId
      if (conversationId && conversationId !== key) {
        useAppStore.getState().intakeRenameConversationKey(key, conversationId)
        const stillHere = useAppStore.getState().currentIntakeConversationId === (key === INTAKE_DRAFT_KEY ? null : key)
        if (stillHere) setCurrentIntakeConversationId(conversationId)
      }
      bumpConversationListVersion()
    }

    const revealTick = () => {
      revealHandle = null

      if (contentQueue) {
        const n = Math.max(BASE_CHARS_PER_FRAME, Math.ceil(contentQueue.length / CATCHUP_DIVISOR))
        useAppStore.getState().intakeAppendStreamToken(key, contentQueue.slice(0, n))
        contentQueue = contentQueue.slice(n)
      }

      if (contentQueue) {
        revealHandle = requestAnimationFrame(revealTick)
      } else if (pendingDone) {
        finalizeDone()
      }
    }

    const scheduleReveal = () => {
      if (revealHandle === null) {
        revealHandle = requestAnimationFrame(revealTick)
      }
    }

    // key 在这里被闭包捕获——即使用户后来切到别的会话，这些回调也一直只写回
    // 当初发消息时所在的那个会话，不会被"当前正在看哪个会话"影响。
    const abort = intakeChatApi.streamMessage(text, key === INTAKE_DRAFT_KEY ? null : key, {
      onToken: (token) => {
        contentQueue += token
        scheduleReveal()
      },
      onTriggerProfileCapture: () => {
        // 只有用户仍然停留在这个会话上时才跳转建档表单——避免另一个在后台
        // 完成生成的会话把用户从当前正在看的会话里"拽走"。
        const stillHere = useAppStore.getState().currentIntakeConversationId === (key === INTAKE_DRAFT_KEY ? null : key)
        if (stillHere) onStartProfile()
      },
      onDone: (conversationId) => {
        // 不立刻收尾——队列里可能还有没吐完的字，等 revealTick 把队列吐空了
        // 再真正 commit，否则最终消息会缺最后一截还没显示出来的文本。
        pendingDone = { conversationId }
        if (!contentQueue) finalizeDone()
        else scheduleReveal()
      },
      onComplianceWarning: () => {},
      onConversationGone: () => {
        // 服务端说这个 conversation_id 不存在/不属于当前身份（孤儿 id）。把刚输入的
        // 消息连同本地会话状态平移到草稿 key，清掉持久化的坏 id，让界面回落到一个
        // 全新会话——用户的消息不丢、重试即以新会话身份重发，而不是死循环打同一个坏 id。
        if (revealHandle !== null) cancelAnimationFrame(revealHandle)
        revealHandle = null
        contentQueue = ''
        const store = useAppStore.getState()
        if (key !== INTAKE_DRAFT_KEY) {
          store.intakeRenameConversationKey(key, INTAKE_DRAFT_KEY)
        }
        store.intakeSetStreaming(INTAKE_DRAFT_KEY, false)
        store.intakeSetLastFailedMessage(INTAKE_DRAFT_KEY, text)
        if (store.currentIntakeConversationId === key) {
          setCurrentIntakeConversationId(null)
        }
        bumpConversationListVersion()
      },
      onError: (msg) => {
        if (revealHandle !== null) cancelAnimationFrame(revealHandle)
        revealHandle = null
        contentQueue = ''
        useAppStore.getState().intakeSetStreaming(key, false)
        useAppStore.getState().intakeSetLastFailedMessage(key, text)
        console.error('Intake chat error:', msg)
      },
      onRateLimit: (msg) => {
        useAppStore.getState().intakeSetDailyLimit(key, true, msg)
        useAppStore.getState().intakeSetStreaming(key, false)
      },
    })
    setIntakeAbort(key, abort)
  }

  const handleRetry = () => {
    if (!lastFailedMessage) return
    const msg = lastFailedMessage
    useAppStore.getState().intakeSetLastFailedMessage(key, null)
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
              className="w-full text-left px-3.5 py-2.5 rounded-card wj-glass-card
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
