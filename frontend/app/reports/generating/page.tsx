'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense } from 'react'
import { CheckCircle, Loader2, XCircle, Clock } from 'lucide-react'
import type { AgentStep, StepStatus } from '@/types'

// Step IDs must match backend mock node names exactly
const INITIAL_STEPS: AgentStep[] = [
  { id: 'data_resolver', label: '解析考生画像', status: 'waiting' },
  { id: 'retrieval_and_rules', label: '检索历年录取数据', status: 'waiting' },
  { id: 'recommendation', label: '生成志愿方案草稿', status: 'waiting' },
  { id: 'risk', label: '风险体检', status: 'waiting' },
  { id: 'report', label: '生成人工复核底稿', status: 'waiting' },
]

function GeneratingContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const runId = searchParams.get('runId') ?? 'demo-run'

  const [steps, setSteps] = useState<AgentStep[]>(INITIAL_STEPS)
  const [overallProgress, setOverallProgress] = useState(0)
  const [status, setStatus] = useState<'running' | 'completed' | 'failed'>('running')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const esRef = useRef<EventSource | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const receivedAnyEvent = useRef(false)

  useEffect(() => {
    timerRef.current = setInterval(() => setElapsedSeconds(s => s + 1), 1000)

    const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    const es = new EventSource(
      `${BASE_URL}/api/v1/agent/runs/${runId}/events`,
      { withCredentials: true }
    )
    esRef.current = es

    const handleNodeStarted = (e: MessageEvent) => {
      receivedAnyEvent.current = true
      try {
        const data = JSON.parse(e.data)
        const { node } = data
        setSteps(prev => prev.map(s => {
          if (s.id === node) return { ...s, status: 'running' }
          if (s.status === 'running') return { ...s, status: 'completed' }
          return s
        }))
        const idx = INITIAL_STEPS.findIndex(s => s.id === node)
        if (idx >= 0) setOverallProgress(Math.round((idx / INITIAL_STEPS.length) * 85))
      } catch {}
    }

    const handleNodeCompleted = (e: MessageEvent) => {
      receivedAnyEvent.current = true
      try {
        const data = JSON.parse(e.data)
        setSteps(prev => prev.map(s => s.id === data.node ? { ...s, status: 'completed' } : s))
      } catch {}
    }

    const handleCompleted = (e: MessageEvent) => {
      receivedAnyEvent.current = true
      try {
        const data = JSON.parse(e.data)
        setStatus('completed')
        setOverallProgress(100)
        setSteps(prev => prev.map(s => s.status === 'waiting' ? s : { ...s, status: 'completed' }))
        es.close()
        if (timerRef.current) clearInterval(timerRef.current)
        const rid = data.report_id ?? 'demo-report'
        setTimeout(() => router.push(`/reports/${rid}`), 1200)
      } catch {}
    }

    const handleServerError = () => {
      receivedAnyEvent.current = true
      setStatus('failed')
      es.close()
      if (timerRef.current) clearInterval(timerRef.current)
    }

    es.addEventListener('node_started', handleNodeStarted)
    es.addEventListener('node_completed', handleNodeCompleted)
    es.addEventListener('completed', handleCompleted)
    es.addEventListener('error', handleServerError)

    // Connection error fallback: only simulate if we never received real events
    es.onerror = () => {
      if (!receivedAnyEvent.current) {
        es.close()
        simulateProgress()
      }
    }

    return () => {
      es.close()
      if (timerRef.current) clearInterval(timerRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const simulateProgress = () => {
    let stepIdx = 0
    const advance = () => {
      if (stepIdx >= INITIAL_STEPS.length) {
        setStatus('completed')
        setOverallProgress(100)
        if (timerRef.current) clearInterval(timerRef.current)
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

  const statusIcon = (s: StepStatus) => {
    switch (s) {
      case 'completed': return <CheckCircle className="w-5 h-5 text-[#16A34A]" />
      case 'running': return <Loader2 className="w-5 h-5 text-[#1E40AF] animate-spin" />
      case 'failed': return <XCircle className="w-5 h-5 text-[#DC2626]" />
      default: return <Clock className="w-5 h-5 text-[#94A3B8]" />
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
        {/* Overall progress */}
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
            {status === 'running' && <span>预计还需 {formatTime(Math.max(0, 90 - elapsedSeconds))}</span>}
            {status === 'completed' && <span className="text-[#16A34A] font-medium">生成完成！正在跳转…</span>}
            {status === 'failed' && <span className="text-[#DC2626]">生成失败，请重试</span>}
          </div>
        </div>

        {/* Step list */}
        <div className="bg-white rounded-card border border-[#E2E8F0] divide-y divide-[#E2E8F0]">
          {steps.map((s) => (
            <div key={s.id} className="flex items-center gap-3 px-4 py-3.5">
              {statusIcon(s.status)}
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
              </div>
            </div>
          ))}
        </div>

        {/* Info box */}
        <div className="bg-[#EFF6FF] rounded-card p-4">
          <p className="text-xs text-[#1E40AF] font-medium mb-1">数据来源说明</p>
          <p className="text-xs text-[#2563EB]">
            基于近 3 年各省高考录取大数据（约 10 万条），结合教育部官方投档线，为你精准匹配。
          </p>
        </div>
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
