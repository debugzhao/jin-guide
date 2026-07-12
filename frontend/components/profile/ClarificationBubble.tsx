'use client'

import { AlertTriangle } from 'lucide-react'
import Button from '@/components/ui/Button'
import type { FieldCheckIssue } from '@/lib/api'

interface Props {
  issue: FieldCheckIssue
  onAction: (action: string) => void
}

/**
 * 建档字段提交后命中矛盾/歧义时的 AI 追问气泡 (docs/frontend-prd-v2.md §6.1
 * 规则前置校验卡片)。选项都是结构化按钮（调整 / 仍按此继续），点击不触发任何
 * LLM 调用——矛盾检测本身就是 Rule Engine 的确定性结果。
 */
export default function ClarificationBubble({ issue, onAction }: Props) {
  return (
    <div className="wj-glass-card rounded-2xl rounded-tl-sm px-4 py-3 max-w-[85%] border-[#FECACA]">
      <div className="flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 text-[#DC2626] flex-shrink-0 mt-0.5" />
        <p className="text-sm text-[#0F172A] leading-relaxed">{issue.message}</p>
      </div>
      <div className="flex gap-2 mt-3">
        {issue.options.map((opt) => (
          <Button key={opt.action} size="sm" variant={opt.action === 'continue_anyway' ? 'ghost' : 'primary'} onClick={() => onAction(opt.action)}>
            {opt.label}
          </Button>
        ))}
      </div>
    </div>
  )
}
