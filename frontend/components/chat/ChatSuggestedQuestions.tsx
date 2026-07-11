'use client'

import { MessageCircle } from 'lucide-react'

const SUGGESTED_QUESTIONS = [
  '为什么推荐这几所学校？',
  '我的安全院校保底够吗？',
  '这份报告的风险点是什么？',
  '如何理解位次差和录取概率？',
]

interface Props {
  onSelect: (question: string) => void
}

export default function ChatSuggestedQuestions({ onSelect }: Props) {
  return (
    <div className="py-5 flex flex-col items-center gap-4">
      <div className="flex flex-col items-center gap-1.5">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[#A78BFA] to-[#7C6CE8]
          flex items-center justify-center">
          <MessageCircle className="w-5 h-5 text-white" />
        </div>
        <p className="text-sm font-medium text-[#F1F5F9]">问问 AI 助手</p>
        <p className="text-xs text-[#6B7280] text-center">
          基于你的志愿报告，解答你的疑问
        </p>
      </div>

      <div className="w-full grid grid-cols-1 gap-2">
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onSelect(q)}
            className="w-full text-left px-3.5 py-2.5 rounded-xl wj-glass-card
              hover:border-[#A78BFA]/40 text-sm text-[#9CA3C4]
              hover:text-[#F1F5F9] transition-colors"
          >
            {q}
          </button>
        ))}
      </div>

      <p className="text-[10px] text-[#6B7280] text-center px-4">
        AI 回复仅供参考，不构成录取承诺。最终填报决定请结合实际情况自主判断。
      </p>
    </div>
  )
}
