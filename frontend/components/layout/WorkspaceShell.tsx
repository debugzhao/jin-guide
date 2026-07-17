'use client'

import { useState } from 'react'
import { FileText, PanelLeftOpen, PanelRightOpen } from 'lucide-react'
import BottomSheet from '@/components/ui/BottomSheet'

interface WorkspaceShellProps {
  sidebar: React.ReactNode
  left: React.ReactNode
  right: React.ReactNode
  /** 报告栏是否已经有内容值得展示；idle 纯聊天阶段为 false，避免空状态占位卡片撑开宽屏布局 */
  hasRight: boolean
  rightCollapsed: boolean
  onToggleRight: () => void
  /** 桌面端左侧导航栏整体折叠；折叠时不卸载 DOM，只隐藏，对齐右栏折叠的处理方式 */
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
  mobileSidebarOpen: boolean
  onCloseMobileSidebar: () => void
}

/**
 * 响应式工作台骨架 (frontend-prd.md §Chat-first 布局)：`/`（AI 对话建档）与
 * `/reports/[id]`（报告工作台）共用同一个骨架组件，区别只在传入内容。
 *
 * 断点策略：
 * - `<lg`（手机/平板）：侧栏收进抽屉，报告收进底部 BottomSheet，主区单栏，
 *   避免窄屏被三栏挤压到不可用（且修复了旧版手机端完全看不到报告的缺口）。
 * - `≥lg`（桌面）：侧栏固定宽常驻 + 对话列（限阅读宽度居中）+ 报告列，
 *   整体壳体加总宽上限，避免超宽屏三栏继续无限拉伸产生新的大片留白。
 *
 * 折叠时不卸载右栏 DOM（只是隐藏），保留已渲染的报告数据
 * （frontend-prd-v2.md §6.1「折叠状态不清空已渲染的报告数据」）。
 */
export default function WorkspaceShell({
  sidebar,
  left,
  right,
  hasRight,
  rightCollapsed,
  onToggleRight,
  sidebarCollapsed,
  onToggleSidebar,
  mobileSidebarOpen,
  onCloseMobileSidebar,
}: WorkspaceShellProps) {
  const [mobileReportOpen, setMobileReportOpen] = useState(false)

  return (
    <div className="flex-1 flex overflow-hidden relative">
      {/* 桌面常驻侧栏：外层做宽度过渡动画，内层固定宽度避免文字挤压变形 */}
      <div
        className={`hidden lg:flex lg:flex-shrink-0 overflow-hidden transition-[width] duration-300 ease-in-out ${
          sidebarCollapsed ? 'lg:w-0' : 'lg:w-[260px]'
        }`}
      >
        <div
          className={`w-[260px] flex-shrink-0 flex flex-col h-full border-r border-[#E2E8F0] bg-white transition-opacity duration-200 ${
            sidebarCollapsed ? 'opacity-0' : 'opacity-100'
          }`}
        >
          {sidebar}
        </div>
      </div>

      {sidebarCollapsed && (
        <button
          onClick={onToggleSidebar}
          className="hidden lg:flex fixed top-6 left-6 items-center gap-2 px-4 py-2.5 rounded-full
            wj-glass-card text-[#0F172A] text-sm shadow-lg hover:border-[#1E40AF]/40 transition-colors z-30"
        >
          <PanelLeftOpen className="w-4 h-4" />
          展开侧栏
        </button>
      )}

      {/* 移动端侧栏抽屉 */}
      {mobileSidebarOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={onCloseMobileSidebar} />
          <div className="absolute left-0 top-0 bottom-0 w-[280px] bg-white shadow-xl flex flex-col">
            {sidebar}
          </div>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden w-full max-w-[1920px] mx-auto">
        <div
          className={
            rightCollapsed || !hasRight
              ? 'flex-1 overflow-y-auto overscroll-contain'
              : 'w-full lg:w-[46%] lg:flex-shrink-0 overflow-y-auto overscroll-contain lg:border-r border-[#E2E8F0]'
          }
        >
          <div className="min-h-full flex flex-col max-w-[760px] mx-auto px-4 py-6">{left}</div>
        </div>

        {hasRight && (
          <div className={rightCollapsed ? 'hidden' : 'hidden lg:block flex-1 overflow-y-auto overscroll-contain bg-[#F8FAFC]'}>
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
        )}

        {hasRight && rightCollapsed && (
          <button
            onClick={onToggleRight}
            className="hidden lg:flex fixed bottom-6 right-6 items-center gap-2 px-4 py-2.5 rounded-full
              wj-glass-card text-[#0F172A] text-sm shadow-lg hover:border-[#1E40AF]/40 transition-colors z-30"
          >
            <PanelRightOpen className="w-4 h-4" />
            展开报告
          </button>
        )}

        {hasRight && (
          <button
            onClick={() => setMobileReportOpen(true)}
            className="lg:hidden fixed bottom-6 right-6 flex items-center gap-2 px-4 py-2.5 rounded-full
              wj-glass-card text-[#0F172A] text-sm shadow-lg z-30"
          >
            <FileText className="w-4 h-4" />
            查看报告
          </button>
        )}
      </div>

      <BottomSheet isOpen={mobileReportOpen} onClose={() => setMobileReportOpen(false)} title="志愿报告">
        {right}
      </BottomSheet>
    </div>
  )
}
