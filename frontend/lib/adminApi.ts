/**
 * Admin Debug Console API — GET /api/v1/admin/*, role=admin only.
 * See backend/app/api/v1/admin.py for the source of truth on response shapes.
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
      // ignore parse errors
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

// All debug event types the backend may emit (without the "debug:" wire prefix)
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
   * Subscribe to the Admin Debug SSE stream for one run (history replay + live).
   * Returns a cleanup function that closes the connection.
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

    // Unnamed "connected" event arrives via the default message handler
    source.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        if (data?.event === 'connected') callbacks.onConnected?.()
      } catch {
        // ignore
      }
    }

    for (const type of DEBUG_EVENT_TYPES) {
      source.addEventListener(`debug:${type}`, (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data)
          callbacks.onEvent(type, data)
        } catch {
          // ignore malformed payloads — best-effort debug stream
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
        // Connection-level error (no data payload) — handled by source.onerror below
      }
    })

    source.onerror = () => {
      callbacks.onError('连接中断')
    }

    return () => source.close()
  },
}
