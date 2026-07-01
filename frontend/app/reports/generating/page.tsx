'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense } from 'react'
import { CheckCircle, Loader2, XCircle, Clock, AlertTriangle } from 'lucide-react'
import type { AgentStep, StepStatus } from '@/types'

// M3 步骤定义，顺序与 LangGraph 节点一致
// retrieval_agent / policy_rule_agent 并行，合并展示为一步
const INITIAL_STEPS: AgentStep[] = [
  { id: 'data_resolver',   label: '档案检查',   status: 'waiting' },
  { id: 'retrieval_agent', label: '数据检索与规则校验', status: 'waiting' },
  { id: 'recommendation',  label: '生成候选方案', status: 'waiting' },
  { id: 'risk',            label: '风险体检',   status: 'waiting' },
  { id: 'report',          label: '生成报告',   status: 'waiting' },
  { id: 'reflection',      label: '合规自检',   status: 'waiting' },
]

// policy_rule_agent 事件映射到同一步骤（并行节点）
const NODE_STEP_MAP: Record<string, string> = {
  policy_rule_agent: 'retrieval_agent',
}

type PageStatus = 'running' | 'completed' | 'failed' | 'interrupted'

interface HumanInterruptData {
  review_task_id: string
  report_id: string
  message: string
  sla_hours: number
  trigger_reasons: string[]
}

function GeneratingContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const runId = searchParams.get('runId') ?? 'demo-run'

  const [steps, setSteps] = useState<AgentStep[]>(INITIAL_STEPS)
  const [overallProgress, setOverallProgress] = useState(0)
  const [pageStatus, setPageStatus] = useState<PageStatus>('running')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [interruptData, setInterruptData] = useState<HumanInterruptData | null>(null)

  const esRef = useRef<EventSource | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectCount = useRef(0)
  const receivedAnyEvent = useRef(false)
  const MAX_RECONNECT = 3

  const connectSSE = (rid: string) => {
    const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    const es = new EventSource(
      `${BASE_URL}/api/v1/agent/runs/${rid}/events`,
      { withCredentials: true }
    )
    esRef.current = es

    es.addEventListener('node_started', (e: MessageEvent) => {
      receivedAnyEvent.current = true
      try {
        const data = JSON.parse(e.data)
        const nodeId: string = NODE_STEP_MAP[data.node] ?? data.node
        setSteps(prev => prev.map(s => {
          if (s.id === nodeId) return { ...s, status: 'running' }
          if (s.status === 'running') return { ...s, status: 'completed' }
          return s
        }))
        const idx = INITIAL_STEPS.findIndex(s => s.id === nodeId)
        if (idx >= 0) setOverallProgress(Math.round((idx / INITIAL_STEPS.length) * 85))
      } catch {}
    })

    es.addEventListener('node_completed', (e: MessageEvent) => {
      receivedAnyEvent.current = true
      try {
        const data = JSON.parse(e.data)
        const nodeId: string = NODE_STEP_MAP[data.node] ?? data.node
        setSteps(prev => prev.map(s => s.id === nodeId ? { ...s, status: 'completed' } : s))
      } catch {}
    })

    es.addEventListener('completed', (e: MessageEvent) => {
      receivedAnyEvent.current = true
      try {
        const data = JSON.parse(e.data)
        setPageStatus('completed')
        setOverallProgress(100)
        setSteps(prev => prev.map(s => ({ ...s, status: 'completed' })))
        es.close()
        clearTimer()
        const reportId = data.report_id ?? 'demo-report'
        setTimeout(() => router.push(`/reports/${reportId}`), 1200)
      } catch {}
    })

    // 高风险或 Reflection 多轮失败时触发人工复核
    es.addEventListener('human_interrupt', (e: MessageEvent) => {
      receivedAnyEvent.current = true
      try {
        const data: HumanInterruptData = JSON.parse(e.data)
        setInterruptData(data)
        setPageStatus('interrupted')
        setOverallProgress(90)
        setSteps(prev => prev.map(s =>
          s.status === 'running' ? { ...s, status: 'completed' } : s
        ))
        es.close()
        clearTimer()
      } catch {}
    })

    es.addEventListener('error', () => {
      receivedAnyEvent.current = true
      setPageStatus('failed')
      setSteps(prev => prev.map(s =>
        s.status === 'running' ? { ...s, status: 'failed' } : s
      ))
      es.close()
      clearTimer()
    })

    // 连接级错误：自动重连（最多3次），超限后降级到模拟
    es.onerror = () => {
      if (!receivedAnyEvent.current) {
        es.close()
        reconnectCount.current++
        if (reconnectCount.current <= MAX_RECONNECT) {
          setTimeout(() => connectSSE(rid), 1500)
        } else {
          simulateProgress()
        }
      }
    }
  }

  const clearTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current)
  }

  useEffect(() => {
    timerRef.current = setInterval(() => setElapsedSeconds(s => s + 1), 1000)
    connectSSE(runId)
    return () => {
      esRef.current?.close()
      clearTimer()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const simulateProgress = () => {
    let stepIdx = 0
    const advance = () => {
      if (stepIdx >= INITIAL_STEPS.length) {
        setPageStatus('completed')
        setOverallProgress(100)
        clearTimer()
        setTimeout(() => router.push('/reports/demo-report'), 1200)
        return
      }
      const nodeId = INITIAL_STEPS[stepIdx].id
      setSteps(prev => prev.map(s => s.id === nodeId ? { ...s, status: 'running' } : s))
      setOverallProgress(Math.round((stepIdx / INITIAL_STEPS.length) * 100))
      setTimeout(() => {
        setSteps(prev => prev.map(s => s.id === nodeId ? { ...s, status: 'completed' } : s))
        stepIdx++
        setTimeout(advance, 400)
      }, 1800 + Math.random() * 800)
    }
    advance()
  }

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return m > 0 ? `${m}分${sec}秒` : `${sec}秒`
  }

  const stepIcon = (s: StepStatus) => {
    switch (s) {
      case 'completed': return <CheckCircle className="w-5 h-5 text-[#16A34A]" />
      case 'running':   return <Loader2 className="w-5 h-5 text-[#1E40AF] animate-spin" />
      case 'failed':    return <XCircle className="w-5 h-5 text-[#DC2626]" />
      default:          return <Clock className="w-5 h-5 text-[#94A3B8]" />
    }
  }

  // ── 复核等待状态 ────────────────────────────────────────────────────────────
  if (pageStatus === 'interrupted' && interruptData) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col">
        <header className="bg-white border-b border-[#E2E8F0] px-4 py-4">
          <div className="max-w-screen-md mx-auto">
            <h1 className="text-base font-semibold text-[#0F172A]">等待人工复核</h1>
            <p className="text-xs text-[#64748B] mt-0.5">报告已生成，正在等待复核员审阅</p>
          </div>
        </header>

        <main className="flex-1 max-w-screen-md mx-auto w-full px-4 py-6 space-y-4">
          {/* SLA 提示卡 */}
          <div className="bg-[#FFFBEB] border border-[#D97706] rounded-card p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-[#D97706] flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-[#92400E]">报告需要人工复核</p>
                <p className="text-xs text-[#B45309] mt-1">
                  {interruptData.message}（预计 {interruptData.sla_hours} 小时内完成）
                </p>
                {interruptData.trigger_reasons.length > 0 && (
                  <p className="text-xs text-[#B45309] mt-1">
                    触发原因：{interruptData.trigger_reasons.join('、')}
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* 已完成步骤 */}
          <div className="bg-white rounded-card border border-[#E2E8F0] divide-y divide-[#E2E8F0]">
            {steps.map((s) => (
              <div key={s.id} className="flex items-center gap-3 px-4 py-3.5">
                {stepIcon(s.status)}
                <p className={`text-sm ${s.status === 'waiting' ? 'text-[#94A3B8]' : 'text-[#0F172A]'}`}>
                  {s.label}
                </p>
              </div>
            ))}
          </div>

          {/* 进入复核页 */}
          <button
            onClick={() => router.push(`/reports/${interruptData.report_id}/review`)}
            className="w-full bg-[#D97706] text-white rounded-btn py-3 text-sm font-medium"
          >
            查看复核详情
          </button>

          <p className="text-xs text-[#94A3B8] text-center">
            您可以先离开页面，复核完成后将收到通知
          </p>
        </main>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] flex flex-col">
      <header className="bg-white border-b border-[#E2E8F0] px-4 py-4">
        <div className="max-w-screen-md mx-auto">
          <h1 className="text-base font-semibold text-[#0F172A]">正在生成志愿方案</h1>
          <p className="text-xs text-[#64748B] mt-0.5">AI 正在分析历年数据，请稍候…</p>
        </div>
      </header>

      <main className="flex-1 max-w-screen-md mx-auto w-full px-4 py-6 space-y-6">
        {/* 总体进度条 */}
        <div className="bg-white rounded-card border border-[#E2E8F0] p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-[#0F172A]">总体进度</span>
            <span className="text-sm font-semibold text-[#1E40AF]">{overallProgress}%</span>
          </div>
          <div className="h-2 bg-[#E2E8F0] rounded-full overflow-hidden">
            <div
              className="h-full bg-[#0D9488] rounded-full transition-all duration-500"
              style={{ width: `${overallProgress}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-xs text-[#64748B]">
            <span>已用时 {formatTime(elapsedSeconds)}</span>
            {pageStatus === 'running' && (
              <span>预计还需 {formatTime(Math.max(0, 90 - elapsedSeconds))}</span>
            )}
            {pageStatus === 'completed' && (
              <span className="text-[#16A34A] font-medium">生成完成！正在跳转…</span>
            )}
            {pageStatus === 'failed' && (
              <span className="text-[#DC2626]">生成失败，请重试</span>
            )}
          </div>
        </div>

        {/* 步骤列表 */}
        <div className="bg-white rounded-card border border-[#E2E8F0] divide-y divide-[#E2E8F0]">
          {steps.map((s) => (
            <div key={s.id} className="flex items-center gap-3 px-4 py-3.5">
              {stepIcon(s.status)}
              <div className="flex-1">
                <p className={`text-sm ${s.status === 'waiting' ? 'text-[#94A3B8]' : 'text-[#0F172A]'}`}>
                  {s.label}
                </p>
                {s.status === 'running' && (
                  <p className="text-xs text-[#1E40AF] mt-0.5">处理中…</p>
                )}
                {s.status === 'completed' && (
                  <p className="text-xs text-[#16A34A] mt-0.5">已完成</p>
                )}
                {s.status === 'failed' && (
                  <p className="text-xs text-[#DC2626] mt-0.5">处理失败</p>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* 超时提示 */}
        {pageStatus === 'running' && elapsedSeconds > 60 && (
          <div className="bg-[#EFF6FF] rounded-card p-4">
            <p className="text-xs text-[#1E40AF]">
              生成时间较长，可以先去做别的事，完成后页面将自动更新结果。
            </p>
          </div>
        )}

        {/* 失败重试 */}
        {pageStatus === 'failed' && (
          <button
            onClick={() => router.back()}
            className="w-full border border-[#DC2626] text-[#DC2626] rounded-btn py-3 text-sm font-medium"
          >
            返回重试
          </button>
        )}

        {pageStatus !== 'failed' && pageStatus !== 'interrupted' && (
          <div className="bg-[#EFF6FF] rounded-card p-4">
            <p className="text-xs text-[#1E40AF] font-medium mb-1">数据来源说明</p>
            <p className="text-xs text-[#2563EB]">
              基于近 3 年各省高考录取大数据（约 10 万条），结合教育部官方投档线，为你精准匹配。
            </p>
          </div>
        )}
      </main>
    </div>
  )
}

export default function GeneratingPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#F8FAFC]" />}>
      <GeneratingContent />
    </Suspense>
  )
}
