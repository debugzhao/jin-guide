'use client'

import { useState } from 'react'
import { Bot, Sparkles } from 'lucide-react'
import ChatInput from '@/components/chat/ChatInput'
import { api } from '@/lib/api'

interface IntakeMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface IntakeChatProps {
  /** 命中建档意图（或用户直接点 CTA）时回调，父组件据此切到 profile 阶段 */
  onStartProfile: () => void
  /** 建档阶段开始后锁定：只保留历史文案，收起欢迎态和输入框，避免和建档表单同时出现两个输入入口 */
  locked: boolean
}

const SUGGESTED_PROMPTS = ['开始志愿建档', '帮我测算一下我的位次', '解读一下一分一段表是什么']

let seq = 0
const nextId = () => `intake-${(seq += 1)}`

/**
 * Chat-first 首屏入口 (docs/frontend-prd-v2.md §Chat-first 建档入口)：默认纯聊天，
 * 只有识别到建档意图后才通过 onStartProfile 让父组件内联渲染 ProfileCaptureCard，
 * 不再是进门就摊开表单。意图判定调 `/profile/intent`（LLM + 关键词兜底，恒可用）。
 */
export default function IntakeChat({ onStartProfile, locked }: IntakeChatProps) {
  const [messages, setMessages] = useState<IntakeMessage[]>([])
  const [classifying, setClassifying] = useState(false)

  const appendMessage = (role: IntakeMessage['role'], content: string) => {
    setMessages((prev) => [...prev, { id: nextId(), role, content }])
  }

  const handleSend = async (text: string) => {
    appendMessage('user', text)
    setClassifying(true)
    try {
      const { intent } = await api.classifyIntent(text)
      if (intent === 'start_profile') {
        appendMessage('assistant', '好的，我们先把生成报告必须依赖的基础信息填一下～')
        onStartProfile()
      } else {
        appendMessage(
          'assistant',
          '这个我可以之后陪你聊；如果想直接开始生成志愿报告，点下面的「开始志愿建档」就行。'
        )
      }
    } catch {
      appendMessage('assistant', '网络好像不太稳定，你可以直接点「开始志愿建档」开始建档。')
    } finally {
      setClassifying(false)
    }
  }

  const handlePromptClick = (prompt: string) => {
    if (prompt === '开始志愿建档') {
      onStartProfile()
      return
    }
    handleSend(prompt)
  }

  const renderedMessages = messages.map((m) =>
    m.role === 'user' ? (
      <div key={m.id} className="flex justify-end">
        <div className="max-w-[80%] px-3.5 py-2.5 rounded-2xl rounded-tr-sm bg-[#EFF6FF] text-[#0F172A] text-sm leading-relaxed break-words">
          {m.content}
        </div>
      </div>
    ) : (
      <div key={m.id} className="flex gap-2 items-start">
        <Bot className="w-5 h-5 text-[#1E40AF] flex-shrink-0 mt-0.5" />
        <div className="max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-tl-sm wj-glass-card text-sm leading-relaxed text-[#0F172A] break-words">
          {m.content}
        </div>
      </div>
    )
  )

  if (locked) {
    if (messages.length === 0) return null
    return <div className="space-y-3">{renderedMessages}</div>
  }

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-5">
        <div className="w-12 h-12 rounded-full bg-gradient-to-br from-[#1E40AF] to-[#2563EB] flex items-center justify-center">
          <Sparkles className="w-6 h-6 text-white" />
        </div>
        <div className="text-center space-y-1">
          <p className="text-base font-semibold text-[#0F172A]">你好，我是问津</p>
          <p className="text-sm text-[#64748B]">说说你的想法，或者直接开始志愿建档</p>
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
          <ChatInput onSend={handleSend} disabled={classifying} placeholder="输入你的问题，或直接说想开始建档…" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col">
      <div className="space-y-3 pb-3">
        {renderedMessages}

        <button onClick={() => handlePromptClick('开始志愿建档')} className="text-xs text-[#1E40AF] hover:underline">
          直接开始志愿建档 →
        </button>
      </div>

      <div className="mt-auto sticky bottom-0 bg-white pt-1">
        <ChatInput onSend={handleSend} disabled={classifying} placeholder="继续聊聊，或直接开始建档…" />
      </div>
    </div>
  )
}
