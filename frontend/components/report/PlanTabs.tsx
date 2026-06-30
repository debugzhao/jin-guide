'use client'

import { cn } from '@/lib/utils'
import type { PlanType } from '@/types'

interface PlanTabsProps {
  currentTab: PlanType
  onChange: (tab: PlanType) => void
}

const tabs: { value: PlanType; label: string; desc: string }[] = [
  { value: 'conservative', label: '保守型', desc: '稳上' },
  { value: 'balanced', label: '均衡型', desc: '推荐' },
  { value: 'aggressive', label: '进取型', desc: '冲高' },
]

export default function PlanTabs({ currentTab, onChange }: PlanTabsProps) {
  return (
    <div className="flex bg-[#F8FAFC] rounded-btn p-1 gap-1">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          onClick={() => onChange(tab.value)}
          className={cn(
            'flex-1 py-2 px-2 rounded-[6px] text-sm font-medium transition-colors',
            'flex flex-col items-center gap-0.5',
            currentTab === tab.value
              ? 'bg-white text-[#1E40AF] shadow-sm'
              : 'text-[#64748B] hover:text-[#0F172A]'
          )}
        >
          <span>{tab.label}</span>
          <span className="text-xs font-normal opacity-70">{tab.desc}</span>
        </button>
      ))}
    </div>
  )
}
