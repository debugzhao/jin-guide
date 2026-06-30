'use client'

import { cn } from '@/lib/utils'
import Card from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import { Clock, CheckSquare } from 'lucide-react'

interface EntryCardProps {
  icon: React.ComponentType<{ className?: string }>
  title: string
  description: string
  materials: string
  estimatedTime: string
  actionLabel: string
  disabled?: boolean
  disabledReason?: string
  onClick?: () => void
  className?: string
}

export default function EntryCard({
  icon: Icon,
  title,
  description,
  materials,
  estimatedTime,
  actionLabel,
  disabled = false,
  disabledReason,
  onClick,
  className,
}: EntryCardProps) {
  return (
    <Card className={cn('wj-entry-card p-4', className)}>
      <div className="wj-entry-head flex items-start gap-3 mb-3">
        <div className="wj-entry-icon w-10 h-10 rounded-btn bg-[#EFF6FF] flex items-center justify-center flex-shrink-0">
          <Icon className="w-5 h-5 text-[#1E40AF]" />
        </div>
        <div className="wj-entry-content flex-1 min-w-0">
          <h2 className="wj-entry-title text-base font-semibold text-[#0F172A] mb-1">{title}</h2>
          <p className="wj-entry-desc text-sm text-[#64748B]">{description}</p>
        </div>
      </div>
      <div className="wj-entry-meta space-y-2 mb-4">
        <div className="wj-entry-meta-row flex items-center gap-1.5 text-xs text-[#64748B]">
          <CheckSquare className="w-3.5 h-3.5 flex-shrink-0" />
          <span>准备材料：{materials}</span>
        </div>
        <div className="wj-entry-meta-row flex items-center gap-1.5 text-xs text-[#64748B]">
          <Clock className="w-3.5 h-3.5 flex-shrink-0" />
          <span>预计耗时：{estimatedTime}</span>
        </div>
      </div>
      {disabled ? (
        <div className="wj-disabled-note text-center py-2">
          <span className="text-sm text-[#94A3B8]">{disabledReason ?? actionLabel}</span>
        </div>
      ) : (
        <Button variant="primary" size="lg" onClick={onClick}>
          {actionLabel}
        </Button>
      )}
    </Card>
  )
}
