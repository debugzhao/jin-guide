const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

export const api = {
  createSession: async () => {
    const res = await apiFetch<{ session_id: string; token: string; expires_at: string }>(
      '/api/v1/auth/session',
      { method: 'POST', body: '{}' }
    )
    return { sessionId: res.session_id, token: res.token }
  },
  createProfile: async (data: unknown) => {
    const res = await apiFetch<{ id: string }>('/api/v1/profile', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    return { profileId: res.id }
  },
  getProfile: (id: string) => apiFetch<unknown>(`/api/v1/profile/${id}`),
  generateReport: async (data: { profileId: string }) => {
    const res = await apiFetch<{ run_id: string; status: string; stream_url: string }>(
      '/api/v1/reports/generate',
      { method: 'POST', body: JSON.stringify({ profile_id: data.profileId }) }
    )
    return { runId: res.run_id }
  },
  getReport: (id: string) => apiFetch<unknown>(`/api/v1/reports/${id}`),
  getRunStatus: (id: string) => apiFetch<unknown>(`/api/v1/agent/runs/${id}`),
}
