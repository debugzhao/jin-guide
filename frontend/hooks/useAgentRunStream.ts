'use client'

import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Agent run 协作事件流 hook —— 统一封装 `GET /api/v1/agent/runs/{id}/events`
 * 的 EventSource 连接、断线重连和兜底轮询，供对话内生成过程卡片（F4）和
 * 实时报告面板（F5）复用，避免像 `reports/generating` 旧页面那样各自重写一遍
 * （docs/backend-prd-v2.md §5.7 用户侧事件白名单）。
 *
 * 只负责"拿到事件流"，不做时间线分组/文案转译——那是 UI 组件（如
 * InlineGenerationCard）的职责。
 */

export interface AgentRunTimelineEvent {
  type: string
  data: Record<string, unknown>
  ts: number
}

export type AgentRunStreamStatus = 'idle' | 'connecting' | 'running' | 'completed' | 'failed'

export interface UseAgentRunStreamResult {
  status: AgentRunStreamStatus
  events: AgentRunTimelineEvent[]
  reportId: string | null
  errorMessage: string | null
}

// 与 docs/backend-prd-v2.md §5.7 用户侧白名单一致
const EVENT_NAMES = [
  'node_started',
  'node_completed',
  'evidence_found',
  'rule_checked',
  'agents_parallel_started',
  'agents_parallel_merged',
  'candidates_ready',
  'risk_found',
  'self_check_round',
  'degraded_notice',
  'profile_incomplete',
  'completed',
  'failed',
  'error',
]

const MAX_RECONNECT = 3
const FALLBACK_POLL_AFTER_MS = 25_000

export function useAgentRunStream(runId: string | null): UseAgentRunStreamResult {
  const [status, setStatus] = useState<AgentRunStreamStatus>('idle')
  const [events, setEvents] = useState<AgentRunTimelineEvent[]>([])
  const [reportId, setReportId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const esRef = useRef<EventSource | null>(null)
  const reconnectCount = useRef(0)
  const receivedAnyEvent = useRef(false)
  const receivedBusinessEvent = useRef(false)
  const settledRef = useRef(false)
  const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!runId) {
      setStatus('idle')
      return
    }

    // demo-run：后端不可达时的本地兜底，直接视为已完成，不建立真实连接
    if (runId === 'demo-run') {
      setStatus('completed')
      setReportId('demo-report')
      return
    }

    settledRef.current = false
    receivedAnyEvent.current = false
    receivedBusinessEvent.current = false
    reconnectCount.current = 0
    setStatus('connecting')
    setEvents([])
    setReportId(null)
    setErrorMessage(null)

    const clearTimers = () => {
      if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current)
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
    }

    const settleCompleted = (rid: string) => {
      if (settledRef.current) return
      settledRef.current = true
      setStatus('completed')
      setReportId(rid)
      esRef.current?.close()
      clearTimers()
    }

    const settleFailed = (message?: string) => {
      if (settledRef.current) return
      settledRef.current = true
      setStatus('failed')
      if (message) setErrorMessage(message)
      esRef.current?.close()
      clearTimers()
    }

    const pushEvent = (type: string, raw: string) => {
      receivedAnyEvent.current = true
      receivedBusinessEvent.current = true
      let data: Record<string, unknown> = {}
      try {
        data = JSON.parse(raw)
      } catch {
        // 非 JSON payload 忽略解析，仍记录事件类型
      }
      setEvents((prev) => [...prev, { type, data, ts: Date.now() }])
      return data
    }

    // 兜底轮询：SSE 长时间没有任何业务事件（例如中间代理断连但未触发 onerror）
    const pollRunAndSettle = async () => {
      if (settledRef.current) return
      try {
        const run = await api.getRunStatus(runId)
        if (run.status === 'completed') {
          const report = await api.getReportByRun(runId)
          settleCompleted(report.id)
          return
        }
        if (run.status === 'failed' || run.status === 'timeout') {
          settleFailed(run.error_msg)
          return
        }
      } catch {
        // run 尚未就绪，继续轮询
      }
      pollTimerRef.current = setTimeout(pollRunAndSettle, 2000)
    }

    const connect = () => {
      const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      const es = new EventSource(`${BASE_URL}/api/v1/agent/runs/${runId}/events`, {
        withCredentials: true,
      })
      esRef.current = es

      es.addEventListener('connected', () => {
        receivedAnyEvent.current = true
        setStatus((s) => (s === 'connecting' ? 'running' : s))
      })

      for (const name of EVENT_NAMES) {
        es.addEventListener(name, (e: MessageEvent) => {
          const data = pushEvent(name, e.data)
          setStatus((s) => (s === 'connecting' ? 'running' : s))

          if (name === 'completed') {
            const rid = typeof data.report_id === 'string' ? data.report_id : undefined
            if (rid) settleCompleted(rid)
            else pollRunAndSettle()
          } else if (name === 'failed' || name === 'error') {
            const msg = typeof data.message === 'string' ? data.message : undefined
            settleFailed(msg)
          }
        })
      }

      es.onerror = () => {
        if (settledRef.current) return
        if (!receivedAnyEvent.current) {
          es.close()
          reconnectCount.current += 1
          if (reconnectCount.current <= MAX_RECONNECT) {
            setTimeout(connect, 1500)
          } else {
            pollRunAndSettle()
          }
        }
      }
    }

    connect()

    fallbackTimerRef.current = setTimeout(() => {
      if (!receivedBusinessEvent.current && !settledRef.current) {
        esRef.current?.close()
        pollRunAndSettle()
      }
    }, FALLBACK_POLL_AFTER_MS)

    return () => {
      esRef.current?.close()
      clearTimers()
    }
  }, [runId])

  return { status, events, reportId, errorMessage }
}
