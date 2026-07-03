import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/**
 * Server-side half of the "服务端 + 客户端双重检查" admin guard (frontend-prd §8.11).
 * Runs before any client JS — anonymous / non-admin visitors never receive the
 * page markup. The client-side re-check lives in AdminDebugShell for the case
 * where the session expires while the tab stays open.
 */
export default async function AdminDebugLayout({ children }: { children: React.ReactNode }) {
  const sessionToken = cookies().get('session_token')?.value

  if (sessionToken) {
    try {
      const res = await fetch(`${BASE_URL}/api/v1/auth/me`, {
        headers: { Cookie: `session_token=${sessionToken}` },
        cache: 'no-store',
      })
      if (res.ok) {
        const me = await res.json()
        if (me?.role === 'admin') {
          return <>{children}</>
        }
      }
    } catch {
      // network/backend error — fall through to redirect, don't leak the console
    }
  }

  redirect('/')
}
