'use client'

import { useMemo, useState } from 'react'
import { Bot, User } from 'lucide-react'
import { api, type FieldCheckIssue } from '@/lib/api'
import { PROFILE_FIELD_ORDER, PROFILE_FIELD_SCHEMA, type ProfileFieldKey } from '@/lib/profileFieldSchema'
import FieldControl from './FieldControl'
import ClarificationBubble from './ClarificationBubble'
import Button from '@/components/ui/Button'

interface AnsweredEntry {
  field: ProfileFieldKey
  question: string
  valueLabel: string
}

interface PendingClarification {
  field: ProfileFieldKey
  value: unknown
  issue: FieldCheckIssue
}

interface ProfileChatFlowProps {
  profileId?: string
  /** 必填字段全部收集完成后由用户点击触发，携带目前已收集的全部字段值 */
  onReady: (values: Record<string, unknown>) => void
  submitting?: boolean
}

function formatValueLabel(field: ProfileFieldKey, value: unknown): string {
  if (value === undefined || value === null || value === '') return '未填写'
  if (Array.isArray(value)) return value.length ? value.join('、') : '不限'
  if (field === 'risk_style') {
    const found = PROFILE_FIELD_SCHEMA.risk_style.options?.find((o) => o.value === value)
    return found?.label.split(' · ')[0] ?? String(value)
  }
  return String(value)
}

/**
 * 对话式建档流：一次问一个字段，逐条渲染已回答的 Q&A + 当前待填字段的结构化
 * 控件。字段顺序/跳过是纯本地计算（`resolved` 集合 vs PROFILE_FIELD_ORDER），
 * 零网络依赖；矛盾检测才调用 `/profile/field-check`（docs/frontend-prd-v2.md
 * §6.1「确定性逻辑与 Agent 边界」表）。
 */
export default function ProfileChatFlow({ profileId, onReady, submitting }: ProfileChatFlowProps) {
  const [answers, setAnswers] = useState<Record<string, unknown>>({})
  const [resolved, setResolved] = useState<Set<string>>(new Set())
  const [log, setLog] = useState<AnsweredEntry[]>([])
  const [clarification, setClarification] = useState<PendingClarification | null>(null)
  const [checking, setChecking] = useState(false)

  const requiredFields = useMemo(
    () => PROFILE_FIELD_ORDER.filter((f) => PROFILE_FIELD_SCHEMA[f].required),
    []
  )
  const requiredDone = requiredFields.every((f) => resolved.has(f))
  const answeredRequiredCount = requiredFields.filter((f) => resolved.has(f)).length
  const progressPercent = Math.round((answeredRequiredCount / requiredFields.length) * 100)

  const activeField = PROFILE_FIELD_ORDER.find((f) => !resolved.has(f)) ?? null

  const commit = (field: ProfileFieldKey, value: unknown) => {
    setAnswers((prev) => ({ ...prev, [field]: value }))
    setResolved((prev) => new Set(prev).add(field))
    setLog((prev) => [
      ...prev,
      { field, question: PROFILE_FIELD_SCHEMA[field].question, valueLabel: formatValueLabel(field, value) },
    ])
    setClarification(null)
  }

  const skip = (field: ProfileFieldKey) => {
    setResolved((prev) => new Set(prev).add(field))
    setLog((prev) => [
      ...prev,
      { field, question: PROFILE_FIELD_SCHEMA[field].question, valueLabel: '未填写' },
    ])
  }

  const handleSubmit = async (field: ProfileFieldKey, value: unknown) => {
    if (value === undefined) {
      skip(field)
      return
    }

    setChecking(true)
    try {
      const knownFields: Record<string, unknown> = { ...answers }
      const result = await api.checkProfileField({ profileId, field, value, knownFields })
      if (result.status === 'needs_clarification' && result.issue) {
        setClarification({ field, value, issue: result.issue })
      } else {
        commit(field, value)
      }
    } catch {
      // field-check 服务不可用时不阻塞建档：按无矛盾处理，仍走确定性字段推进
      commit(field, value)
    } finally {
      setChecking(false)
    }
  }

  const handleClarificationAction = (action: string) => {
    if (!clarification) return
    if (action === 'continue_anyway') {
      commit(clarification.field, clarification.value)
    } else {
      // 调整类 action：清空追问，交回同一个字段的控件让用户重新填写
      setClarification(null)
    }
  }

  return (
    <div className="space-y-4">
      {log.map((entry, i) => (
        <div key={i} className="space-y-2">
          <div className="flex gap-2 items-start">
            <Bot className="w-5 h-5 text-[#A78BFA] flex-shrink-0 mt-0.5" />
            <p className="text-sm text-[#F1F5F9]">{entry.question}</p>
          </div>
          <div className="flex gap-2 items-start justify-end">
            <div className="max-w-[80%] px-3.5 py-2 rounded-2xl rounded-tr-sm bg-[rgba(169,180,245,0.12)] text-sm text-[#F1F5F9]">
              {entry.valueLabel}
            </div>
            <User className="w-5 h-5 text-[#9CA3C4] flex-shrink-0 mt-0.5" />
          </div>
        </div>
      ))}

      {clarification && (
        <div className="space-y-2">
          <div className="flex gap-2 items-start">
            <Bot className="w-5 h-5 text-[#F2A9A9] flex-shrink-0 mt-0.5" />
            <ClarificationBubble issue={clarification.issue} onAction={handleClarificationAction} />
          </div>
        </div>
      )}

      {!clarification && activeField && (
        <div className="space-y-2">
          <div className="flex gap-2 items-start">
            <Bot className="w-5 h-5 text-[#A78BFA] flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm text-[#F1F5F9]">{PROFILE_FIELD_SCHEMA[activeField].question}</p>
              {PROFILE_FIELD_SCHEMA[activeField].helpText && (
                <p className="text-xs text-[#9CA3C4] mt-0.5">{PROFILE_FIELD_SCHEMA[activeField].helpText}</p>
              )}
            </div>
          </div>
          <div className="pl-7">
            <FieldControl
              key={activeField}
              entry={PROFILE_FIELD_SCHEMA[activeField]}
              onSubmit={(value) => handleSubmit(activeField, value)}
            />
            {checking && <p className="text-xs text-[#9CA3C4] mt-1.5">校验中...</p>}
          </div>
        </div>
      )}

      {requiredDone && (
        <div className="wj-glass-card rounded-card px-4 py-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-[#9CA3C4]">基础信息进度</span>
            <span className="text-xs text-[#8FE0B7]">{progressPercent}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-white/10">
            <div className="h-full rounded-full bg-[#8FE0B7]" style={{ width: `${progressPercent}%` }} />
          </div>
          <Button className="w-full mt-1" onClick={() => onReady(answers)} disabled={submitting}>
            {submitting ? '生成中...' : '确认基础信息并渲染报告'}
          </Button>
        </div>
      )}
    </div>
  )
}
