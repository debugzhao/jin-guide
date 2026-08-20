/**
 * Admin Debug Console 的 API 封装——GET /api/v1/admin/*，无鉴权、仅供 admin 场景使用。
 * 响应结构以 backend/app/api/v1/admin.py 为准。
 */
const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function adminFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { credentials: 'include' })
  if (!res.ok) {
    let message = `API error ${res.status}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') message = body.detail
    } catch {
      // 忽略解析错误
    }
    throw new Error(message)
  }
  return res.json()
}

export interface AdminRunSummary {
  id: string
  status: string
  task_type: string
  profile_id: string | null
  cost_usd: number
  cost_tokens: number
  duration_seconds: number | null
  trace_url: string | null
  error_msg: string | null
  degraded_agents: string[]
  triggered_human_review: boolean
  node_count_completed: number
  created_at: string
  completed_at: string | null
}

export interface AdminRunDetail extends Omit<AdminRunSummary, 'node_count_completed'> {
  thread_id: string
  debug_summary_json: {
    node_timings?: Record<string, number>
    tool_call_summary?: { tool: string; count: number; success: number; error: number; avg_latency_ms: number }[]
    state_summary?: Record<string, unknown>
    degraded_agents?: string[]
    cost_breakdown?: { cost_usd: number; cost_tokens: number }
  } | null
}

export interface AdminMetricsSummary {
  total_runs_24h: number
  completed_runs_24h: number
  failed_runs_24h: number
  error_rate_pct: number
  avg_duration_seconds: number | null
  total_cost_usd_24h: number
  active_runs: number
  timestamp: number
}

// 后端可能发出的所有调试事件类型（不含线上传输时的 "debug:" 前缀）
const DEBUG_EVENT_TYPES = [
  'node_started',
  'node_completed',
  'tool_called',
  'degraded',
  'circuit_breaker',
  'parallel_fan_out',
  'parallel_fan_in',
  'reflection_iteration',
  'state_checkpoint',
  'stream_end',
] as const

export const adminApi = {
  listRuns: (params?: { limit?: number; status?: string }) => {
    const qs = new URLSearchParams()
    if (params?.limit) qs.set('limit', String(params.limit))
    if (params?.status) qs.set('status', params.status)
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return adminFetch<AdminRunSummary[]>(`/api/v1/admin/runs${suffix}`)
  },

  getRun: (runId: string) => adminFetch<AdminRunDetail>(`/api/v1/admin/runs/${runId}`),

  getMetricsSummary: () => adminFetch<AdminMetricsSummary>('/api/v1/admin/metrics/summary'),

  /**
   * 订阅某次 run 的 Admin Debug SSE 流（先回放历史事件、再接续实时事件）。
   * 返回一个用于关闭连接的清理函数。
   */
  streamDebugEvents: (
    runId: string,
    callbacks: {
      onConnected?: () => void
      onEvent: (type: (typeof DEBUG_EVENT_TYPES)[number], data: Record<string, unknown>) => void
      onStreamEnd?: () => void
      onError: (message: string) => void
    }
  ): (() => void) => {
    const source = new EventSource(`${BASE_URL}/api/v1/admin/runs/${runId}/debug-events`, {
      withCredentials: true,
    })

    // 未命名的 "connected" 事件走的是默认 message handler
    source.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        if (data?.event === 'connected') callbacks.onConnected?.()
      } catch {
        // 忽略
      }
    }

    for (const type of DEBUG_EVENT_TYPES) {
      source.addEventListener(`debug:${type}`, (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data)
          callbacks.onEvent(type, data)
        } catch {
          // 忽略格式异常的负载——调试流本身是 best-effort，不追求绝对可靠
        }
        if (type === 'stream_end') {
          callbacks.onStreamEnd?.()
          source.close()
        }
      })
    }

    source.addEventListener('error', (ev: MessageEvent) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data)
        callbacks.onError(data?.message ?? '未知错误')
      } catch {
        // 连接级错误（没有 data 负载）——交给下面的 source.onerror 处理
      }
    })

    source.onerror = () => {
      callbacks.onError('连接中断')
    }

    return () => source.close()
  },
}
