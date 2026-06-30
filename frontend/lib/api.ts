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
  createSession: () =>
    apiFetch<{ sessionId: string }>('/api/v1/auth/session', {
      method: 'POST',
      body: '{}',
    }),
  createProfile: (data: unknown) =>
    apiFetch<{ profileId: string }>('/api/v1/profile', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getProfile: (id: string) => apiFetch<unknown>(`/api/v1/profile/${id}`),
  generateReport: (data: unknown) =>
    apiFetch<{ runId: string; reportId: string }>('/api/v1/reports/generate', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getReport: (id: string) => apiFetch<unknown>(`/api/v1/reports/${id}`),
  getRunStatus: (id: string) => apiFetch<unknown>(`/api/v1/agent/runs/${id}`),
}
