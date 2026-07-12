'use client'

import { useCallback, useState } from 'react'
import ProfileChatFlow from '@/components/profile/ProfileChatFlow'
import InlineGenerationCard from '@/components/chat/InlineGenerationCard'
import ChatColumn from '@/components/chat/ChatColumn'
import Button from '@/components/ui/Button'
import { api } from '@/lib/api'
import { useAppStore } from '@/lib/store'

type Stage = 'profile' | 'generating' | 'chat'

interface ConversationStreamProps {
  /** 报告拿到 report_id 后回调，供 `/` 页面把地址栏无刷新切换为 /reports/[id] */
  onReportReady: (reportId: string) => void
}

function buildProfileSummaryLabel(answers: Record<string, unknown>): string {
  const parts: string[] = []
  if (typeof answers.province === 'string') parts.push(answers.province)
  if (typeof answers.score === 'number') parts.push(`${answers.score} 分`)
  if (typeof answers.rank === 'number') parts.push(`位次 ${answers.rank}`)
  if (Array.isArray(answers.subjects)) parts.push((answers.subjects as string[]).join('/'))
  return parts.join(' · ')
}

/**
 * `/` 页面左侧对话流（F2）：建档 → 生成过程 → 报告问答三个阶段的同一条对话，
 * 不是三个独立页面（frontend-prd-v2.md §0「Generative UI 混合形态」）。
 */
export default function ConversationStream({ onReportReady }: ConversationStreamProps) {
  const { setProfileId } = useAppStore()
  const [stage, setStage] = useState<Stage>('profile')
  const [runId, setRunId] = useState<string | null>(null)
  const [reportId, setReportId] = useState<string | null>(null)
  const [profileSummaryLabel, setProfileSummaryLabel] = useState('')
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [lastAnswers, setLastAnswers] = useState<Record<string, unknown> | null>(null)

  const handleProfileReady = async (answers: Record<string, unknown>) => {
    setSubmitting(true)
    setGenerationError(null)
    setLastAnswers(answers)
    setProfileSummaryLabel(buildProfileSummaryLabel(answers))

    const payload = {
      province: answers.province,
      batch: answers.batch ?? '本科批',
      score: answers.score,
      rank: answers.rank,
      subjects: answers.subjects,
      family_budget: answers.family_budget,
      risk_style: answers.risk_style,
      preference: {
        city_prefs: answers.city_prefs ?? [],
        major_prefs: answers.major_prefs ?? [],
      },
    }

    try {
      const { profileId } = await api.createProfile(payload)
      setProfileId(profileId)
      const { runId: rid } = await api.generateReport({ profileId })
      setRunId(rid)
      setStage('generating')
    } catch {
      // 后端不可达时的本地兜底演示路径，与旧版 /reports/generating 行为一致
      setRunId('demo-run')
      setStage('generating')
    } finally {
      setSubmitting(false)
    }
  }

  const handleGenerationComplete = useCallback(
    (rid: string) => {
      setReportId(rid)
      setStage('chat')
      onReportReady(rid)
    },
    [onReportReady]
  )

  const handleGenerationFailed = useCallback((message?: string) => {
    setGenerationError(message || '生成失败，请重试')
  }, [])

  const handleRetry = () => {
    if (lastAnswers) handleProfileReady(lastAnswers)
  }

  return (
    <div className="space-y-4">
      <ProfileChatFlow onReady={handleProfileReady} submitting={submitting} />

      {stage !== 'profile' && runId && (
        <InlineGenerationCard
          runId={runId}
          profileSummaryLabel={profileSummaryLabel}
          onComplete={handleGenerationComplete}
          onFailed={handleGenerationFailed}
        />
      )}

      {generationError && stage === 'generating' && (
        <div className="wj-glass-card rounded-card px-4 py-3 border-[#FECACA] space-y-2">
          <p className="text-sm text-[#DC2626]">{generationError}</p>
          <Button size="sm" variant="outline" onClick={handleRetry}>返回修改</Button>
        </div>
      )}

      {stage === 'chat' && reportId && (
        <div className="pt-2 border-t border-[#E2E8F0]">
          <ChatColumn reportId={reportId} />
        </div>
      )}
    </div>
  )
}
