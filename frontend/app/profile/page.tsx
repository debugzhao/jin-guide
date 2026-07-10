'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import TopNav from '@/components/layout/TopNav'
import ProfileChatFlow from '@/components/profile/ProfileChatFlow'
import { api } from '@/lib/api'
import { useAppStore } from '@/lib/store'

/**
 * 对话式建档页。字段收集逻辑由 ProfileChatFlow + FieldControl + 后端
 * /profile/field-check 驱动（docs/frontend-prd-v2.md §6.1）。本页只负责：
 * 必填字段收集完成后打包提交 createProfile → generateReport。
 *
 * 这是 F3（结构化控件渲染器）范围内的最小可用集成；页面骨架本身（与报告
 * 工作台合并为左右双栏、实时报告面板）属于 F2，尚未在此落地。
 */
export default function ProfilePage() {
  const router = useRouter()
  const { setProfileId } = useAppStore()
  const [submitting, setSubmitting] = useState(false)

  const handleReady = async (answers: Record<string, unknown>) => {
    setSubmitting(true)
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
      const { runId } = await api.generateReport({ profileId })
      router.push(`/reports/generating?runId=${runId}`)
    } catch {
      router.push(`/reports/generating?runId=demo-run`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen">
      <TopNav title="AI 对话建档" showBack onBack={() => router.back()} />
      <main className="max-w-screen-md mx-auto px-4 py-6">
        <ProfileChatFlow onReady={handleReady} submitting={submitting} />
      </main>
    </div>
  )
}

