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
    <div className="px-4 py-5 flex flex-col items-center gap-4">
      <div className="flex flex-col items-center gap-1.5">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600
          flex items-center justify-center">
          <MessageCircle className="w-5 h-5 text-white" />
        </div>
        <p className="text-sm font-medium text-gray-800">问问 AI 助手</p>
        <p className="text-xs text-gray-400 text-center">
          基于你的志愿报告，解答你的疑问
        </p>
      </div>

      <div className="w-full grid grid-cols-1 gap-2">
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onSelect(q)}
            className="w-full text-left px-3.5 py-2.5 rounded-xl border border-gray-200
              bg-gray-50 hover:bg-blue-50 hover:border-blue-200 text-sm text-gray-700
              hover:text-blue-700 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>

      <p className="text-[10px] text-gray-400 text-center px-4">
        AI 回复仅供参考，不构成录取承诺。最终填报决定请结合实际情况自主判断。
      </p>
    </div>
  )
}
