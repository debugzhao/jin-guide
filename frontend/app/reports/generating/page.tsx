'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense } from 'react'
import { CheckCircle, Loader2, XCircle, Clock } from 'lucide-react'
import { api } from '@/lib/api'
import type { AgentStep, StepStatus } from '@/types'

const INITIAL_STEPS: AgentStep[] = [
  { id: 'data_resolver',   label: '档案检查',         status: 'waiting' },
  { id: 'retrieval_agent', label: '数据检索与规则校验', status: 'waiting' },
  { id: 'recommendation',  label: '生成候选方案',       status: 'waiting' },
  { id: 'risk',            label: '风险体检',           status: 'waiting' },
  { id: 'report',          label: '生成报告',           status: 'waiting' },
  { id: 'reflection',      label: '合规自检',           status: 'waiting' },
]

const NODE_STEP_MAP: Record<string, string> = {
  policy_rule_agent: 'retrieval_agent',
}

type PageStatus = 'running' | 'completed' | 'failed'

function GeneratingContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const runId = searchParams.get('runId') ?? 'demo-run'

  const [steps, setSteps] = useState<AgentStep[]>(INITIAL_STEPS)
  const [overallProgress, setOverallProgress] = useState(0)
  const [pageStatus, setPageStatus] = useState<PageStatus>('running')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  const esRef = useRef<EventSource | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectCount = useRef(0)
  const receivedAnyEvent = useRef(false)
  const hasReceivedBusinessEvent = useRef(false)
  const redirectedRef = useRef(false)
  const fallbackTriggeredRef = useRef(false)
  const MAX_RECONNECT = 3

  const clearTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current)
  }

  const clearPollTimer = () => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
  }

  const redirectToReport = (reportId: string) => {
    if (redirectedRef.current) return
    redirectedRef.current = true
    setPageStatus('completed')
    setOverallProgress(100)
    setSteps(prev => prev.map(s => ({ ...s, status: 'completed' })))
    esRef.current?.close()
    clearTimer()
    clearPollTimer()
    setTimeout(() => router.push(`/reports/${reportId}`), 1200)
  }

  const markFailed = () => {
    setPageStatus('failed')
    setSteps(prev => prev.map(s =>
      s.status === 'running' ? { ...s, status: 'failed' } : s
    ))
    esRef.current?.close()
    clearTimer()
    clearPollTimer()
  }

  const pollRunAndRedirect = (rid: string) => {
    if (rid === 'demo-run') {
      redirectToReport('demo-report')
      return
    }

    const poll = async () => {
      if (redirectedRef.current) return
      try {
        const run = await api.getRunStatus(rid)
        if (run.status === 'completed') {
          const report = await api.getReportByRun(rid)
          redirectToReport(report.id)
          return
        }
        if (run.status === 'failed') {
          markFailed()
          return
        }
      } catch {
        // run/report 尚未就绪，继续轮询
      }
      pollTimerRef.current = setTimeout(poll, 2000)
    }

    poll()
  }

  const connectSSE = (rid: string) => {
    const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    const es = new EventSource(
      `${BASE_URL}/api/v1/agent/runs/${rid}/events`,
      { withCredentials: true }
    )
    esRef.current = es

    es.addEventListener('connected', () => {
      receivedAnyEvent.current = true
    })

    es.addEventListener('node_started', (e: MessageEvent) => {
      receivedAnyEvent.current = true
      hasReceivedBusinessEvent.current = true
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
      hasReceivedBusinessEvent.current = true
      try {
        const data = JSON.parse(e.data)
        const nodeId: string = NODE_STEP_MAP[data.node] ?? data.node
        setSteps(prev => prev.map(s => s.id === nodeId ? { ...s, status: 'completed' } : s))
      } catch {}
    })

    es.addEventListener('completed', (e: MessageEvent) => {
      receivedAnyEvent.current = true
      hasReceivedBusinessEvent.current = true
      try {
        const data = JSON.parse(e.data)
        const reportId = data.report_id as string | undefined
        if (reportId) {
          redirectToReport(reportId)
        } else {
          pollRunAndRedirect(rid)
        }
      } catch {
        pollRunAndRedirect(rid)
      }
    })

    es.addEventListener('failed', () => {
      receivedAnyEvent.current = true
      hasReceivedBusinessEvent.current = true
      markFailed()
    })

    es.addEventListener('error', () => {
      receivedAnyEvent.current = true
      hasReceivedBusinessEvent.current = true
      markFailed()
    })

    es.onerror = () => {
      if (!receivedAnyEvent.current) {
        es.close()
        reconnectCount.current++
        if (reconnectCount.current <= MAX_RECONNECT) {
          setTimeout(() => connectSSE(rid), 1500)
        } else {
          pollRunAndRedirect(rid)
        }
      }
    }
  }

  useEffect(() => {
    if (runId === 'demo-run') {
      redirectToReport('demo-report')
      return
    }

    timerRef.current = setInterval(() => {
      setElapsedSeconds(s => {
        const next = s + 1
        if (next >= 25 && !hasReceivedBusinessEvent.current && !fallbackTriggeredRef.current) {
          fallbackTriggeredRef.current = true
          esRef.current?.close()
          pollRunAndRedirect(runId)
        }
        return next
      })
    }, 1000)
    connectSSE(runId)
    return () => {
      esRef.current?.close()
      clearTimer()
      clearPollTimer()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

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

  return (
    <div className="min-h-screen bg-[#F8FAFC] flex flex-col">
      <header className="bg-white border-b border-[#E2E8F0] px-4 py-4">
        <div className="max-w-screen-md mx-auto">
          <h1 className="text-base font-semibold text-[#0F172A]">正在生成志愿方案</h1>
          <p className="text-xs text-[#64748B] mt-0.5">AI 正在分析历年数据，请稍候…</p>
        </div>
      </header>

      <main className="flex-1 max-w-screen-md mx-auto w-full px-4 py-6 space-y-6">
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

        {pageStatus === 'running' && elapsedSeconds > 60 && (
          <div className="bg-[#EFF6FF] rounded-card p-4">
            <p className="text-xs text-[#1E40AF]">
              生成时间较长，可以先去做别的事，完成后页面将自动更新结果。
            </p>
          </div>
        )}

        {pageStatus === 'failed' && (
          <button
            onClick={() => router.back()}
            className="w-full border border-[#DC2626] text-[#DC2626] rounded-btn py-3 text-sm font-medium"
          >
            返回重试
          </button>
        )}

        {pageStatus !== 'failed' && (
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
