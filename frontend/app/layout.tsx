import type { Metadata } from 'next'
import './globals.css'
import { ToastContainer } from '@/components/ui/Toast'

export const metadata: Metadata = {
  title: '问津 Agent',
  description: 'AI 志愿决策助理',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body className="bg-[#F8FAFC] min-h-screen" style={{ fontFamily: '-apple-system, "PingFang SC", "Noto Sans SC", "Helvetica Neue", sans-serif' }}>
        {children}
        <ToastContainer />
      </body>
    </html>
  )
}
