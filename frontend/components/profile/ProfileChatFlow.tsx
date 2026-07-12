'use client'

import { useState } from 'react'
import { Bot } from 'lucide-react'
import ProfileCaptureCard from './ProfileCaptureCard'
import CapturedInfoSummary from './CapturedInfoSummary'
import ProfileSummaryStatus from './ProfileSummaryStatus'
import PreferenceComposer, { type PreferenceEntry } from './PreferenceComposer'
import PreferenceCard from './PreferenceCard'

interface ProfileChatFlowProps {
  profileId?: string
  /** 必填字段全部收集完成后由用户点击触发，携带目前已收集的全部字段值 */
  onReady: (values: Record<string, unknown>) => void
  submitting?: boolean
}

/**
 * 对话式建档流的顶层编排：说明气泡 → 「基础建档信息」卡片（一次性网格表单，
 * 不是逐条提问）→ 提交后展示「已采集信息」「档案摘要」两张卡片 + 底部自然
 * 语言输入框补充偏好（docs/wenjin-agent-prototype.html 第 1039-1131 行是
 * 当前交互事实源）。
 */
export default function ProfileChatFlow({ profileId, onReady, submitting }: ProfileChatFlowProps) {
  const [capturedValues, setCapturedValues] = useState<Record<string, unknown> | null>(null)
  const [preferenceLog, setPreferenceLog] = useState<PreferenceEntry[]>([])

  const handleCaptureSubmit = (values: Record<string, unknown>) => {
    setCapturedValues(values)
    onReady(values)
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 items-start">
        <Bot className="w-5 h-5 text-[#1E40AF] flex-shrink-0 mt-0.5" />
        <p className="text-sm text-[#0F172A]">
          我会用对话方式帮你完成建档。左侧收集信息，右侧实时渲染志愿报告；后续补充城市、专业或学费偏好时，右侧报告会继续更新。
        </p>
      </div>

      {!capturedValues && (
        <ProfileCaptureCard profileId={profileId} onSubmit={handleCaptureSubmit} submitting={submitting} />
      )}

      {capturedValues && (
        <>
          <CapturedInfoSummary values={capturedValues} />
          <ProfileSummaryStatus
            hasPreferences={preferenceLog.some((p) => p.matched)}
            reportVersion={preferenceLog.some((p) => p.matched) ? 'preference_updated' : 'basic'}
          />
          {preferenceLog.map((entry) => (
            <PreferenceCard key={entry.id} entry={entry} />
          ))}
          <PreferenceComposer onSubmit={(entry) => setPreferenceLog((prev) => [...prev, entry])} />
        </>
      )}
    </div>
  )
}
