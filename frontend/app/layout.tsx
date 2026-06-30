import type { Metadata } from 'next'
import './globals.css'
import { ToastContainer } from '@/components/ui/Toast'

const criticalCss = `
  *, ::before, ::after { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; }
  body {
    background: #F8FAFC;
    color: #0F172A;
    font-family: -apple-system, "PingFang SC", "Noto Sans SC", "Helvetica Neue", sans-serif;
  }
  .wj-shell { min-height: 100vh; background: #F8FAFC; }
  .wj-header { background: #FFFFFF; border-bottom: 1px solid #E2E8F0; padding: 16px; }
  .wj-header-inner {
    max-width: 768px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }
  .wj-title { margin: 0; color: #1E40AF; font-size: 20px; line-height: 28px; font-weight: 700; }
  .wj-subtitle { margin: 2px 0 0; color: #64748B; font-size: 12px; line-height: 16px; }
  .wj-main { max-width: 768px; margin: 0 auto; padding: 24px 16px; }
  .wj-main > * + * { margin-top: 16px; }
  .wj-kicker { margin: 0 0 8px; color: #64748B; font-size: 14px; line-height: 20px; }
  .wj-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  }
  .wj-entry-card { padding: 16px; }
  .wj-entry-head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
  .wj-entry-icon {
    width: 40px;
    height: 40px;
    flex: 0 0 auto;
    border-radius: 8px;
    background: #EFF6FF;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .wj-entry-icon svg { width: 20px; height: 20px; color: #1E40AF; }
  .wj-entry-content { flex: 1 1 auto; min-width: 0; }
  .wj-entry-title { margin: 0 0 4px; color: #0F172A; font-size: 16px; line-height: 24px; font-weight: 600; }
  .wj-entry-desc { margin: 0; color: #64748B; font-size: 14px; line-height: 20px; }
  .wj-entry-meta { margin-bottom: 16px; }
  .wj-entry-meta > * + * { margin-top: 8px; }
  .wj-entry-meta-row { display: flex; align-items: center; gap: 6px; color: #64748B; font-size: 12px; line-height: 16px; }
  .wj-entry-meta-row svg { width: 14px; height: 14px; flex: 0 0 auto; }
  .wj-button {
    border: 0;
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-family: inherit;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 150ms ease, color 150ms ease, opacity 150ms ease;
  }
  .wj-button:disabled { cursor: not-allowed; opacity: 0.5; }
  .wj-button-primary { background: #1E40AF; color: #FFFFFF; }
  .wj-button-primary:not(:disabled):hover { background: #1E3A8A; }
  .wj-button-outline { border: 1px solid #1E40AF; background: transparent; color: #1E40AF; }
  .wj-button-ghost { background: transparent; color: #64748B; }
  .wj-button-ghost:not(:disabled):hover { background: #F1F5F9; }
  .wj-button-sm { padding: 6px 12px; font-size: 14px; line-height: 20px; }
  .wj-button-md { padding: 10px 16px; font-size: 16px; line-height: 24px; }
  .wj-button-lg { width: 100%; padding: 12px 24px; font-size: 18px; line-height: 28px; }
  .wj-disabled-note { padding: 8px 0; text-align: center; color: #94A3B8; font-size: 14px; line-height: 20px; }
`

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
      <head>
        <style dangerouslySetInnerHTML={{ __html: criticalCss }} />
      </head>
      <body className="bg-[#F8FAFC] min-h-screen" style={{ fontFamily: '-apple-system, "PingFang SC", "Noto Sans SC", "Helvetica Neue", sans-serif' }}>
        {children}
        <ToastContainer />
      </body>
    </html>
  )
}
