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
  .wj-topnav {
    position: sticky;
    top: 0;
    z-index: 30;
    height: 64px;
    background: rgba(255, 255, 255, 0.96);
    border-bottom: 1px solid #E2E8F0;
    backdrop-filter: blur(12px);
  }
  .wj-topnav-inner {
    max-width: 1120px;
    height: 100%;
    margin: 0 auto;
    padding: 0 24px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .wj-topnav-back {
    width: 36px;
    height: 36px;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    background: #FFFFFF;
    color: #0F172A;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
  }
  .wj-topnav-back svg { width: 20px; height: 20px; }
  .wj-topnav-title { margin: 0; flex: 1; color: #0F172A; font-size: 18px; line-height: 28px; font-weight: 700; }
  .wj-profile-shell { min-height: 100vh; background: #F8FAFC; }
  .wj-profile-main {
    max-width: 1120px;
    margin: 0 auto;
    padding: 32px 24px 56px;
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    gap: 24px;
  }
  .wj-profile-sidebar,
  .wj-profile-panel {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 18px;
    box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
  }
  .wj-profile-sidebar { padding: 20px; align-self: start; }
  .wj-profile-panel { padding: 28px; }
  .wj-stepper-card { background: transparent; border: 0; padding: 0; }
  .wj-stepper-title { margin: 2px 0 0; color: #0F172A; font-size: 18px; line-height: 28px; font-weight: 700; }
  .wj-stepper-meta { color: #64748B; font-size: 13px; line-height: 20px; }
  .wj-stepper-progress { height: 8px; margin-bottom: 18px; border-radius: 999px; background: #E2E8F0; overflow: hidden; }
  .wj-stepper-progress-bar { height: 100%; border-radius: inherit; background: #0D9488; transition: width 300ms ease; }
  .wj-stepper-dots { display: flex; gap: 8px; margin-top: 18px; }
  .wj-step-dot {
    width: 18px;
    height: 18px;
    border-radius: 999px;
    background: #E2E8F0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .wj-step-dot.is-completed { background: #0D9488; }
  .wj-step-dot.is-current { background: #1E40AF; }
  .wj-step-dot svg { width: 12px; height: 12px; color: #FFFFFF; }
  .wj-step-dot-inner { width: 6px; height: 6px; border-radius: 999px; background: #FFFFFF; }
  .wj-profile-form { max-width: 640px; }
  .wj-profile-form > * + * { margin-top: 22px; }
  .wj-field-label { display: block; margin-bottom: 8px; color: #0F172A; font-size: 14px; line-height: 20px; font-weight: 600; }
  .wj-field-help { color: #64748B; font-size: 12px; line-height: 18px; }
  .wj-input,
  .wj-select {
    width: 100%;
    height: 44px;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    background: #FFFFFF;
    color: #0F172A;
    padding: 0 12px;
    font: inherit;
    font-size: 14px;
    outline: none;
  }
  .wj-input:focus,
  .wj-select:focus {
    border-color: #1E40AF;
    box-shadow: 0 0 0 3px rgba(30, 64, 175, 0.16);
  }
  .wj-choice-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  .wj-choice-card {
    min-height: 44px;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    background: #FFFFFF;
    color: #64748B;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    font-size: 14px;
    cursor: pointer;
  }
  .wj-choice-card:has(input:checked) {
    border-color: #1E40AF;
    background: #EFF6FF;
    color: #1E40AF;
    font-weight: 600;
  }
  .wj-actions { display: flex; gap: 12px; padding-top: 8px; }
  .wj-actions .wj-button { flex: 1; min-height: 44px; }
  @media (max-width: 900px) {
    .wj-profile-main { display: block; padding: 24px 16px 40px; }
    .wj-profile-sidebar { margin-bottom: 16px; }
  }
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
