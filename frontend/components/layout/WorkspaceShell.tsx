'use client'

import { PanelRightOpen } from 'lucide-react'

interface WorkspaceShellProps {
  left: React.ReactNode
  right: React.ReactNode
  rightCollapsed: boolean
  onToggleRight: () => void
}

/**
 * 桌面端左右双栏工作台骨架 (F2, frontend-prd-v2.md §6.1/§6.2)：左侧持续对话，
 * 右侧报告画布。`/`（AI 对话建档）与 `/reports/[id]`（报告工作台）共用同一个
 * 骨架组件，区别只在传入的 left/right 内容。
 *
 * 折叠时不卸载右栏 DOM（只是隐藏），保留已渲染的报告数据
 * （frontend-prd-v2.md §6.1「折叠状态不清空已渲染的报告数据」）。
 */
export default function WorkspaceShell({ left, right, rightCollapsed, onToggleRight }: WorkspaceShellProps) {
  return (
    <div className="flex-1 flex overflow-hidden">
      <div className={rightCollapsed ? 'flex-1 overflow-y-auto' : 'w-full md:w-[42%] md:flex-shrink-0 overflow-y-auto border-r border-[#E2E8F0]'}>
        <div className="max-w-screen-sm mx-auto px-4 py-6">{left}</div>
      </div>

      <div className={rightCollapsed ? 'hidden' : 'hidden md:block flex-1 overflow-y-auto bg-[#F8FAFC]'}>
        <div className="max-w-screen-md mx-auto px-4 py-6">
          <button
            onClick={onToggleRight}
            className="mb-3 text-xs text-[#64748B] hover:text-[#0F172A] transition-colors"
          >
            收起报告
          </button>
          {right}
        </div>
      </div>

      {rightCollapsed && (
        <button
          onClick={onToggleRight}
          className="hidden md:flex fixed bottom-6 right-6 items-center gap-2 px-4 py-2.5 rounded-full
            wj-glass-card text-[#0F172A] text-sm shadow-lg hover:border-[#1E40AF]/40 transition-colors z-30"
        >
          <PanelRightOpen className="w-4 h-4" />
          展开报告
        </button>
      )}
    </div>
  )
}
