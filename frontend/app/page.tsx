import { cookies } from 'next/headers'
import HomeClient, { type InitialAuthState } from './HomeClient'
import type { CurrentUser } from '@/lib/store'

/** 在服务端首屏确定登录态，避免登录区等待客户端 JS 下载和 hydration。 */
async function getInitialAuth(): Promise<InitialAuthState> {
  const sessionToken = cookies().get('session_token')?.value
  if (!sessionToken) return { checked: true, user: null }

  const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
  try {
    const response = await fetch(`${backendUrl}/api/v1/auth/me`, {
      headers: { cookie: `session_token=${encodeURIComponent(sessionToken)}` },
      cache: 'no-store',
    })
    if (response.status === 401) return { checked: true, user: null }
    if (!response.ok) return { checked: false, user: null }
    return { checked: true, user: (await response.json()) as CurrentUser }
  } catch {
    // 后端短暂不可用时交给客户端再探测一次，避免把网络故障误判成退出登录。
    return { checked: false, user: null }
  }
}

export const dynamic = 'force-dynamic'

export default async function HomePage() {
  return <HomeClient initialAuth={await getInitialAuth()} />
}
