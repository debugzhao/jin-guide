'use client'

import { useEffect, useMemo, useState } from 'react'
import { Bot, CheckCircle2, ChevronDown, ChevronUp, Loader2, XCircle } from 'lucide-react'
import { useAgentRunStream, type AgentRunTimelineEvent } from '@/hooks/useAgentRunStream'

type StepStatus = 'pending' | 'running' | 'completed'

interface ReflectionRound {
  iteration: number
  maxIterations: number
  issueCategory: string
  status: string
}

interface Derived {
  dataResolver: StepStatus
  parallel: StepStatus
  parallelDetails: string[]
  recommendation: StepStatus
  candidatesSummary: string | null
  risk: StepStatus
  riskSummary: string[]
  report: StepStatus
  reflectionRounds: ReflectionRound[]
  degradedNotices: string[]
}

const ISSUE_CATEGORY_LABEL: Record<string, string> = {
  over_promise: '发现表述可能构成过度承诺',
  evidence_gap: '证据引用不完整',
  none: '检查通过',
}

function deriveTimeline(events: AgentRunTimelineEvent[]): Derived {
  const d: Derived = {
    dataResolver: 'pending',
    parallel: 'pending',
    parallelDetails: [],
    recommendation: 'pending',
    candidatesSummary: null,
    risk: 'pending',
    riskSummary: [],
    report: 'pending',
    reflectionRounds: [],
    degradedNotices: [],
  }

  for (const evt of events) {
    const node = typeof evt.data.node === 'string' ? evt.data.node : undefined

    switch (evt.type) {
      case 'node_started':
        if (node === 'data_resolver') d.dataResolver = 'running'
        else if (node === 'recommendation') {
          d.dataResolver = 'completed'
          d.parallel = d.parallel === 'pending' ? 'completed' : d.parallel
          d.recommendation = 'running'
        } else if (node === 'risk') {
          d.recommendation = 'completed'
          d.risk = 'running'
        } else if (node === 'report') {
          d.risk = 'completed'
          d.report = 'running'
        }
        break
      case 'agents_parallel_started':
        d.dataResolver = 'completed'
        d.parallel = 'running'
        break
      case 'agents_parallel_merged':
        d.parallel = 'completed'
        break
      case 'evidence_found': {
        const count = evt.data.source_count
        const msg = typeof evt.data.message === 'string' ? evt.data.message : `已发现 ${count ?? ''} 条证据`
        d.parallelDetails.push(msg)
        break
      }
      case 'rule_checked': {
        const target = typeof evt.data.target === 'string' ? evt.data.target : ''
        const status = evt.data.status
        d.parallelDetails.push(`规则校验${target ? `（${target}）` : ''}：${status === 'passed' ? '通过' : String(status)}`)
        break
      }
      case 'candidates_ready': {
        d.recommendation = 'completed'
        const total = evt.data.total ?? 0
        d.candidatesSummary = `已完成（共 ${total} 所候选）`
        break
      }
      case 'risk_found': {
        const msg = typeof evt.data.message === 'string' ? evt.data.message : '发现风险项'
        d.riskSummary.push(msg)
        break
      }
      case 'self_check_round': {
        d.report = 'completed'
        const iteration = Number(evt.data.iteration ?? d.reflectionRounds.length + 1)
        const round: ReflectionRound = {
          iteration,
          maxIterations: Number(evt.data.max_iterations ?? 3),
          issueCategory: String(evt.data.issue_category ?? 'none'),
          status: String(evt.data.status ?? 'passed'),
        }
        const existingIdx = d.reflectionRounds.findIndex((r) => r.iteration === iteration)
        if (existingIdx >= 0) d.reflectionRounds[existingIdx] = round
        else d.reflectionRounds.push(round)
        break
      }
      case 'degraded_notice': {
        const msg = typeof evt.data.message === 'string' ? evt.data.message : '检索遇到延迟，已切换备用数据源'
        d.degradedNotices.push(msg)
        break
      }
      case 'completed':
        d.report = 'completed'
        d.risk = 'completed'
        d.recommendation = 'completed'
        d.parallel = 'completed'
        d.dataResolver = 'completed'
        break
      default:
        break
    }
  }

  return d
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'completed') return <CheckCircle2 className="w-4 h-4 text-[#16A34A]" />
  if (status === 'running') return <Loader2 className="w-4 h-4 text-[#1E40AF] animate-spin" />
  return <span className="w-4 h-4 rounded-full border border-[#CBD5E1] inline-block" />
}

interface InlineGenerationCardProps {
  runId: string
  profileSummaryLabel?: string
  onComplete: (reportId: string) => void
  onFailed?: (message?: string) => void
}

/**
 * 对话内生成过程卡片 (F4, frontend-prd-v2.md §6.1「对话内生成过程卡片」表)。
 * 默认展示精简摘要，可展开查看并行处理/自我检查完整时间线；不阻塞右侧实时
 * 报告面板同时渲染。事件来自 useAgentRunStream，均为真实执行产生的信号，
 * 不是编造的动画。
 */
export default function InlineGenerationCard({
  runId,
  profileSummaryLabel,
  onComplete,
  onFailed,
}: InlineGenerationCardProps) {
  const { status, events, reportId, errorMessage } = useAgentRunStream(runId)
  const [expanded, setExpanded] = useState(false)
  const derived = useMemo(() => deriveTimeline(events), [events])

  useEffect(() => {
    if (status === 'completed' && reportId) onComplete(reportId)
  }, [status, reportId, onComplete])

  useEffect(() => {
    if (status === 'failed') onFailed?.(errorMessage ?? undefined)
  }, [status, errorMessage, onFailed])

  const summaryText =
    status === 'failed'
      ? '生成失败，请稍后重试'
      : status === 'completed'
        ? '报告已生成'
        : derived.report === 'running' || derived.reflectionRounds.length > 0
          ? 'AI 正在自我检查报告内容...'
          : derived.risk !== 'pending'
            ? '正在体检志愿梯度...'
            : derived.recommendation !== 'pending'
              ? '正在生成候选方案...'
              : derived.parallel !== 'pending'
                ? '正在同时检索数据和校验规则...'
                : '正在锁定数据版本...'

  return (
    <div className="wj-glass-card rounded-card px-4 py-3 space-y-2 max-w-[90%]">
      <div className="flex items-start gap-2">
        <Bot className="w-4 h-4 text-[#1E40AF] flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-[#0F172A]">方案生成过程</p>
          {profileSummaryLabel && (
            <p className="text-xs text-[#64748B] mt-0.5">{profileSummaryLabel}</p>
          )}
        </div>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-[#64748B] hover:text-[#0F172A] flex-shrink-0"
          aria-label={expanded ? '收起时间线' : '展开时间线'}
        >
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>

      {!expanded && (
        <div className="flex items-center gap-2 pl-6">
          {status === 'failed' ? (
            <XCircle className="w-4 h-4 text-[#DC2626]" />
          ) : status === 'completed' ? (
            <CheckCircle2 className="w-4 h-4 text-[#16A34A]" />
          ) : (
            <Loader2 className="w-4 h-4 text-[#1E40AF] animate-spin" />
          )}
          <p className="text-sm text-[#0F172A]">{summaryText}</p>
        </div>
      )}

      {expanded && (
        <div className="pl-6 space-y-2 text-sm">
          <div className="flex items-center gap-2">
            <StepIcon status={derived.dataResolver} />
            <span className="text-[#0F172A]">档案检查 / 数据版本锁定</span>
          </div>

          <div className="rounded-btn bg-[#F8FAFC] border border-[#BFDBFE] px-3 py-2 space-y-1">
            <div className="flex items-center gap-2">
              <StepIcon status={derived.parallel} />
              <span className="text-[#0F172A]">正在并行处理：检索招生数据 + 校验选科/体检/批次规则</span>
            </div>
            {derived.parallelDetails.map((msg, i) => (
              <p key={i} className="text-xs text-[#64748B] pl-6">→ {msg}</p>
            ))}
          </div>

          {derived.degradedNotices.map((msg, i) => (
            <p key={i} className="text-xs text-[#2563EB] pl-6">ℹ️ {msg}</p>
          ))}

          <div className="flex items-center gap-2">
            <StepIcon status={derived.recommendation} />
            <span className="text-[#0F172A]">生成候选方案 {derived.candidatesSummary ?? ''}</span>
          </div>

          <div className="flex items-start gap-2">
            <StepIcon status={derived.risk} />
            <div>
              <span className="text-[#0F172A]">志愿梯度体检</span>
              {derived.riskSummary.map((msg, i) => (
                <p key={i} className="text-xs text-[#D97706] mt-0.5">{msg}</p>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <StepIcon status={derived.report} />
            <span className="text-[#0F172A]">生成报告初稿</span>
          </div>

          {derived.reflectionRounds.length > 0 && (
            <div className="rounded-btn bg-[#F8FAFC] border border-[#BFDBFE] px-3 py-2 space-y-1">
              <p className="text-[#0F172A]">AI 正在自我检查</p>
              {derived.reflectionRounds.map((r) => (
                <p key={r.iteration} className="text-xs text-[#64748B]">
                  第 {r.iteration} 轮：{ISSUE_CATEGORY_LABEL[r.issueCategory] ?? r.issueCategory}
                  {r.status === 'passed' ? ' ✓' : ' → 正在修正...'}
                </p>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2">
            <StepIcon status={status === 'completed' ? 'completed' : 'pending'} />
            <span className="text-[#0F172A]">
              {status === 'failed' ? '生成失败' : status === 'completed' ? '报告已生成' : '报告交付'}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
