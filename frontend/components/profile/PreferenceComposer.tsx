'use client'

import { useState } from 'react'
import { Send } from 'lucide-react'
import Button from '@/components/ui/Button'

export interface PreferenceEntry {
  id: string
  text: string
  matched: boolean
}

interface PreferenceComposerProps {
  onSubmit: (entry: PreferenceEntry) => void
}

// 与 docs/wenjin-agent-prototype.html sendConversation() 里的 preferenceIntent 正则一致，
// 用于判断自由文本是否命中城市/专业/学费类偏好意图。
const PREFERENCE_INTENT = /(城市|上海|北京|广州|深圳|杭州|南京|长三角|省内|专业|计算机|自动化|电子|学费|预算|费用|万|护理|医学)/

/**
 * 底部自然语言输入框 —— 报告生成后用于补充城市/专业/学费偏好或已有志愿草稿
 * （docs/wenjin-agent-prototype.html 第 1128-1131 行「继续补充城市、专业、
 * 学费偏好或已有志愿草稿」）。当前只做意图识别 + 展示"推荐偏好"卡片，
 * 真正把偏好转成 `/refine` patch 并重新生成报告是 F6（ConversationAgent
 * tool-calling）的范围，尚未接通。
 */
export default function PreferenceComposer({ onSubmit }: PreferenceComposerProps) {
  const [text, setText] = useState('')

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    onSubmit({ id: `${Date.now()}`, text: trimmed, matched: PREFERENCE_INTENT.test(trimmed) })
    setText('')
  }

  return (
    <div className="sticky bottom-0 wj-glass-card rounded-2xl p-2.5 flex items-center gap-2 mt-2">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        maxLength={200}
        placeholder="继续补充城市、专业、学费偏好或已有志愿草稿"
        className="flex-1 bg-transparent text-sm text-[#0F172A] placeholder:text-[#94A3B8] outline-none min-h-[36px] px-1"
      />
      <Button size="sm" onClick={handleSend} disabled={!text.trim()}>
        <Send className="w-3.5 h-3.5" />
      </Button>
    </div>
  )
}
