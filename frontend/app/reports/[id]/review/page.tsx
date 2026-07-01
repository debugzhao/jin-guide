'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import TopNav from '@/components/layout/TopNav'
import Card from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import EmptyState from '@/components/ui/EmptyState'
import { reviewApi, type ReviewOut } from '@/lib/api'
import { cn } from '@/lib/utils'

type ReviewStatus = 'pending' | 'in_review' | 'need_more_info' | 'reviewed' | 'closed' | 'timeout'

const STATUS_CONFIG: Record<ReviewStatus, { label: string; bg: string; text: string }> = {
  pending: { label: '待复核', bg: 'bg-[#EFF6FF]', text: 'text-[#2563EB]' },
  in_review: { label: '复核中', bg: 'bg-[#EFF6FF]', text: 'text-[#2563EB]' },
  need_more_info: { label: '需要补充', bg: 'bg-[#FFFBEB]', text: 'text-[#D97706]' },
  reviewed: { label: '已复核', bg: 'bg-[#F0FDF4]', text: 'text-[#16A34A]' },
  closed: { label: '已关闭', bg: 'bg-[#F1F5F9]', text: 'text-[#64748B]' },
  timeout: { label: '已超时', bg: 'bg-[#FEF2F2]', text: 'text-[#DC2626]' },
}

const SEVERITY_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  high: AlertCircle,
  medium: AlertTriangle,
  low: CheckCircle,
}

const SEVERITY_COLOR: Record<string, string> = {
  high: 'text-[#DC2626]',
  medium: 'text-[#D97706]',
  low: 'text-[#16A34A]',
}

export default function HumanReviewPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  const [review, setReview] = useState<ReviewOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draftExpanded, setDraftExpanded] = useState(true)

  useEffect(() => {
    if (!id) return
    reviewApi
      .getByReportId(id)
      .then((item) => {
        if (!item) return null
        return reviewApi.get(item.id)
      })
      .then(setReview)
      .catch((e: Error) => setError(e.message || '加载复核信息失败'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center gap-3">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <p className="text-sm text-gray-400">加载复核信息中...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center gap-3">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-sm text-gray-600">{error}</p>
        <button onClick={() => router.back()} className="text-sm text-blue-600 underline">返回</button>
      </div>
    )
  }

  if (!review) {
    return (
      <div className="min-h-screen bg-[#F8FAFC]">
        <TopNav title="人工复核" showBack onBack={() => router.push(`/reports/${id}`)} />
        <EmptyState
          className="mt-10"
          title="暂无复核记录"
          description="该报告目前还没有人工复核申请"
          actionLabel="返回报告"
          onAction={() => router.push(`/reports/${id}`)}
        />
      </div>
    )
  }

  const status = (review.status as ReviewStatus) || 'pending'
  const statusConfig = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending
  const checklist = review.checklist_json
  const riskItems = checklist?.risk_items ?? []

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      <TopNav title="人工复核" showBack onBack={() => router.push(`/reports/${id}`)} />

      <main className="max-w-screen-md mx-auto px-4 py-5 space-y-4 pb-10">
        {/* 状态栏 */}
        <Card className={cn('p-0 overflow-hidden')}>
          <div className={cn('px-4 py-3 flex items-center gap-3', statusConfig.bg)}>
            <Clock className={cn('w-5 h-5', statusConfig.text)} />
            <div>
              <p className="text-xs text-[#64748B]">复核状态</p>
              <p className={cn('text-base font-bold', statusConfig.text)}>{statusConfig.label}</p>
            </div>
          </div>
        </Card>

        {/* AI 咨询底稿 */}
        {checklist && (
          <Card className="p-0 overflow-hidden">
            <button
              onClick={() => setDraftExpanded((v) => !v)}
              className="w-full flex items-center justify-between px-4 py-3"
            >
              <span className="text-sm font-semibold text-[#0F172A]">AI 咨询底稿</span>
              {draftExpanded ? (
                <ChevronUp className="w-4 h-4 text-[#64748B]" />
              ) : (
                <ChevronDown className="w-4 h-4 text-[#64748B]" />
              )}
            </button>
            {draftExpanded && (
              <div className="px-4 pb-4 space-y-3 border-t border-[#E2E8F0] pt-3">
                <p className="text-sm text-[#0F172A]">{checklist.summary}</p>
                {checklist.reviewer_checklist?.length > 0 && (
                  <ul className="space-y-1.5">
                    {checklist.reviewer_checklist.map((c) => (
                      <li key={c.id} className="text-xs text-[#64748B] flex items-start gap-1.5">
                        <span className="mt-0.5">·</span>
                        <span>{c.item}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </Card>
        )}

        {/* 高风险清单 */}
        {riskItems.length > 0 && (
          <Card>
            <p className="text-sm font-semibold text-[#0F172A] mb-3">高风险清单</p>
            <div className="space-y-2.5">
              {riskItems.map((item, i) => {
                const Icon = SEVERITY_ICON[item.severity] ?? AlertTriangle
                const color = SEVERITY_COLOR[item.severity] ?? SEVERITY_COLOR.medium
                return (
                  <div key={i} className="flex items-start gap-2">
                    {status === 'reviewed' ? (
                      <CheckCircle className="w-4 h-4 mt-0.5 flex-shrink-0 text-[#16A34A]" />
                    ) : (
                      <Icon className={cn('w-4 h-4 mt-0.5 flex-shrink-0', color)} />
                    )}
                    <div className="flex-1">
                      <p className="text-sm text-[#0F172A]">{item.message}</p>
                      {item.targets?.length > 0 && (
                        <p className="text-xs text-[#64748B] mt-0.5">涉及：{item.targets.join('、')}</p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
        )}

        {/* 需要补充信息 */}
        {status === 'need_more_info' && (
          <Card className="bg-[#FFFBEB] border-[#D97706]">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-[#D97706] flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-[#92400E]">复核员要求补充信息</p>
                <p className="text-xs text-[#B45309] mt-1">
                  {review.reviewer_notes || '请通过客服渠道补充相关信息，我们会尽快跟进。'}
                </p>
              </div>
            </div>
          </Card>
        )}

        {/* 复核结论 */}
        {status === 'reviewed' && (
          <Card>
            <p className="text-sm font-semibold text-[#0F172A] mb-2">复核结论</p>
            <div className="flex items-center gap-2 mb-2">
              {review.conclusion === 'approved' ? (
                <CheckCircle className="w-5 h-5 text-[#16A34A]" />
              ) : (
                <XCircle className="w-5 h-5 text-[#DC2626]" />
              )}
              <span className={cn('text-sm font-medium', review.conclusion === 'approved' ? 'text-[#16A34A]' : 'text-[#DC2626]')}>
                {review.conclusion === 'approved' ? '方案已通过复核' : '方案需要调整'}
              </span>
            </div>
            {review.reviewer_notes && (
              <p className="text-sm text-[#0F172A] mb-2">{review.reviewer_notes}</p>
            )}
            <p className="text-xs text-[#94A3B8]">
              复核员{review.reviewer_id ? `（${review.reviewer_id}）` : ''} · {review.completed_at?.slice(0, 16).replace('T', ' ')}
            </p>
          </Card>
        )}

        {(status === 'pending' || status === 'in_review') && (
          <p className="text-xs text-[#94A3B8] text-center">
            复核完成后将自动更新此页面，您可以先离开页面稍后查看
          </p>
        )}

        <Button variant="outline" size="lg" onClick={() => router.push(`/reports/${id}`)}>
          返回报告
        </Button>
      </main>
    </div>
  )
}
