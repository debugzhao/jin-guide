'use client'

import { useEffect, useState } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  RefreshCw,
} from 'lucide-react'
import TopNav from '@/components/layout/TopNav'
import Card from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Skeleton from '@/components/ui/Skeleton'
import EmptyState from '@/components/ui/EmptyState'
import { useToastStore } from '@/components/ui/Toast'
import { reviewApi, type ReviewListItem, type ReviewOut } from '@/lib/api'
import { useAppStore } from '@/lib/store'
import { cn } from '@/lib/utils'

type TabKey = 'pending' | 'in_review' | 'need_more_info' | 'reviewed'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'pending', label: '待复核' },
  { key: 'in_review', label: '进行中' },
  { key: 'need_more_info', label: '需补充' },
  { key: 'reviewed', label: '已完成' },
]

function slaLabel(timeoutAt: string | null): { text: string; urgent: boolean } {
  if (!timeoutAt) return { text: '无 SLA', urgent: false }
  const diffMs = new Date(timeoutAt).getTime() - Date.now()
  if (diffMs <= 0) return { text: '已超时', urgent: true }
  const totalMinutes = Math.floor(diffMs / 60000)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return {
    text: `剩余 ${hours > 0 ? `${hours}小时` : ''}${minutes}分`,
    urgent: diffMs < 60 * 60 * 1000, // < 1h left (created > 3h ago on a 4h SLA)
  }
}

function ReviewerGate() {
  const { setReviewerId } = useAppStore()
  const [name, setName] = useState('')

  return (
    <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center px-4 gap-4">
      <p className="text-sm text-[#64748B]">请输入复核员姓名以继续</p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="复核员姓名"
        className="w-full max-w-xs border border-[#E2E8F0] rounded-btn px-3 py-2 text-sm"
      />
      <Button
        variant="primary"
        size="md"
        disabled={!name.trim()}
        onClick={() => setReviewerId(name.trim())}
      >
        进入工作台
      </Button>
    </div>
  )
}

function ReviewDetailPanel({
  reviewId,
  onDone,
}: {
  reviewId: string
  onDone: () => void
}) {
  const { reviewerId } = useAppStore()
  const { addToast } = useToastStore()
  const [detail, setDetail] = useState<ReviewOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [verdicts, setVerdicts] = useState<Record<string, 'pass' | 'flag'>>({})
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setLoading(true)
    reviewApi
      .get(reviewId)
      .then(setDetail)
      .catch(() => addToast('error', '加载复核详情失败'))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewId])

  const checklist = detail?.checklist_json
  const requiredItems = checklist?.reviewer_checklist?.filter((c) => c.required) ?? []
  const canSubmit = requiredItems.every((c) => verdicts[c.id])

  const handleSubmit = async (conclusion: 'approved' | 'rejected' | 'need_more_info') => {
    if (!reviewerId || submitting) return
    if (conclusion !== 'need_more_info' && !canSubmit) return
    setSubmitting(true)
    try {
      await reviewApi.submitConclusion(reviewId, {
        conclusion,
        reviewer_id: reviewerId,
        reviewer_notes: notes || undefined,
        checklist_results: Object.entries(verdicts).map(([id, verdict]) => ({ id, verdict })),
      })
      addToast('success', '复核结论已提交')
      onDone()
    } catch {
      addToast('error', '提交失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <Skeleton variant="card" className="h-40" />
  }
  if (!checklist) {
    return <p className="text-sm text-[#94A3B8] px-4 py-3">该复核暂无底稿</p>
  }

  return (
    <div className="border-t border-[#E2E8F0] px-4 py-4 space-y-4 bg-[#F8FAFC]">
      {/* AI 底稿 */}
      <div>
        <p className="text-xs font-semibold text-[#0F172A] mb-1">AI 咨询底稿</p>
        <p className="text-sm text-[#334155]">{checklist.summary}</p>
      </div>

      {/* 风险清单 */}
      {checklist.risk_items?.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-[#0F172A] mb-1.5">风险清单</p>
          <div className="space-y-1.5">
            {checklist.risk_items.map((item, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                <AlertTriangle
                  className={cn(
                    'w-4 h-4 mt-0.5 flex-shrink-0',
                    item.severity === 'high' ? 'text-[#DC2626]' : 'text-[#D97706]'
                  )}
                />
                <span className="text-[#0F172A]">{item.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Checklist 逐项判断 */}
      {checklist.reviewer_checklist?.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-[#0F172A] mb-1.5">复核清单</p>
          <div className="space-y-2">
            {checklist.reviewer_checklist.map((c) => (
              <div key={c.id} className="flex items-center justify-between gap-3 bg-white rounded-btn border border-[#E2E8F0] px-3 py-2">
                <span className="text-sm text-[#0F172A] flex-1">
                  {c.item}
                  {c.required && <span className="text-[#DC2626] ml-1">*</span>}
                </span>
                <div className="flex gap-1.5 flex-shrink-0">
                  <button
                    onClick={() => setVerdicts((v) => ({ ...v, [c.id]: 'pass' }))}
                    className={cn(
                      'px-2.5 py-1 rounded-btn text-xs font-medium border',
                      verdicts[c.id] === 'pass'
                        ? 'bg-[#F0FDF4] border-[#16A34A] text-[#16A34A]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    )}
                  >
                    通过
                  </button>
                  <button
                    onClick={() => setVerdicts((v) => ({ ...v, [c.id]: 'flag' }))}
                    className={cn(
                      'px-2.5 py-1 rounded-btn text-xs font-medium border',
                      verdicts[c.id] === 'flag'
                        ? 'bg-[#FEF2F2] border-[#DC2626] text-[#DC2626]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    )}
                  >
                    标记
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="复核备注（需补充信息时必填说明原因）"
        className="w-full border border-[#E2E8F0] rounded-btn px-3 py-2 text-sm resize-none"
        rows={2}
      />

      <div className="flex gap-2">
        <Button
          variant="primary"
          size="md"
          disabled={submitting || !canSubmit}
          onClick={() => handleSubmit('approved')}
        >
          通过
        </Button>
        <Button
          variant="outline"
          size="md"
          disabled={submitting || !canSubmit}
          onClick={() => handleSubmit('rejected')}
        >
          拒绝
        </Button>
        <Button
          variant="ghost"
          size="md"
          disabled={submitting || !notes.trim()}
          onClick={() => handleSubmit('need_more_info')}
        >
          需要补充
        </Button>
      </div>
      {requiredItems.length > 0 && !canSubmit && (
        <p className="text-xs text-[#DC2626]">请先完成所有必填复核项（*）再提交通过/拒绝</p>
      )}
    </div>
  )
}

function ReviewRow({
  review,
  onClaimed,
  onSubmitted,
}: {
  review: ReviewListItem
  onClaimed: (updated: ReviewListItem) => void
  onSubmitted: () => void
}) {
  const { reviewerId } = useAppStore()
  const { addToast } = useToastStore()
  const [expanded, setExpanded] = useState(false)
  const [claiming, setClaiming] = useState(false)
  const sla = slaLabel(review.timeout_at)

  const handleClaim = async () => {
    if (!reviewerId || claiming) return
    setClaiming(true)
    try {
      const updated = await reviewApi.claim(review.id, reviewerId)
      onClaimed({
        id: updated.id,
        report_id: updated.report_id,
        run_id: updated.run_id,
        status: updated.status,
        conclusion: updated.conclusion,
        created_at: updated.created_at,
        timeout_at: updated.timeout_at,
      })
      setExpanded(true)
    } catch {
      addToast('error', '领取失败，任务可能已被其他复核员领取')
    } finally {
      setClaiming(false)
    }
  }

  return (
    <Card className="p-0 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        <Clock className={cn('w-4 h-4 flex-shrink-0', sla.urgent ? 'text-[#DC2626]' : 'text-[#64748B]')} />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[#0F172A] truncate">复核任务 #{review.id.slice(0, 8)}</p>
          <p className={cn('text-xs mt-0.5', sla.urgent ? 'text-[#DC2626] font-medium' : 'text-[#64748B]')}>
            {review.created_at.slice(0, 16).replace('T', ' ')} · {sla.text}
          </p>
        </div>
        {review.status === 'pending' && (
          <Button
            variant="primary"
            size="sm"
            disabled={claiming}
            onClick={(e) => { e.stopPropagation(); handleClaim() }}
          >
            领取
          </Button>
        )}
        {expanded ? <ChevronUp className="w-4 h-4 text-[#94A3B8]" /> : <ChevronDown className="w-4 h-4 text-[#94A3B8]" />}
      </button>
      {expanded && review.status !== 'pending' && (
        <ReviewDetailPanel reviewId={review.id} onDone={onSubmitted} />
      )}
      {expanded && review.status === 'pending' && (
        <p className="text-xs text-[#94A3B8] px-4 py-3 border-t border-[#E2E8F0]">请先领取任务再查看详情</p>
      )}
    </Card>
  )
}

export default function AdminReviewsPage() {
  const { reviewerId, setReviewerId } = useAppStore()
  const [tab, setTab] = useState<TabKey>('pending')
  const [reviews, setReviews] = useState<ReviewListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    reviewApi
      .list(tab)
      .then(setReviews)
      .catch((e: Error) => setError(e.message || '加载失败'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!reviewerId) return
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, reviewerId])

  if (!reviewerId) return <ReviewerGate />

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      <TopNav
        title="复核员工作台"
        rightSlot={
          <button
            onClick={() => setReviewerId(null)}
            className="text-xs text-[#64748B] hover:text-[#0F172A]"
          >
            {reviewerId} · 切换
          </button>
        }
      />

      <div className="max-w-screen-md mx-auto px-4 pt-4 flex gap-1 border-b border-[#E2E8F0]">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'px-3 py-2 text-sm font-medium border-b-2 -mb-px',
              tab === t.key
                ? 'border-[#1E40AF] text-[#1E40AF]'
                : 'border-transparent text-[#64748B]'
            )}
          >
            {t.label}
          </button>
        ))}
        <button onClick={load} className="ml-auto p-2 text-[#64748B]" aria-label="刷新">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      <main className="max-w-screen-md mx-auto px-4 py-4 space-y-3">
        {loading && (
          <>
            <Skeleton variant="card" className="h-16" />
            <Skeleton variant="card" className="h-16" />
          </>
        )}

        {!loading && error && (
          <div className="flex items-center gap-2 text-sm text-[#DC2626] py-6 justify-center">
            <AlertCircle className="w-4 h-4" />
            {error}
          </div>
        )}

        {!loading && !error && reviews.length === 0 && (
          <EmptyState icon={CheckCircle} title="暂无任务" description="当前分类下没有待处理的复核任务" />
        )}

        {!loading &&
          reviews.map((r) => (
            <ReviewRow
              key={r.id}
              review={r}
              onClaimed={(updated) => setReviews((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))}
              onSubmitted={load}
            />
          ))}
      </main>
    </div>
  )
}
