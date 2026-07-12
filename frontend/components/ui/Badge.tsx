import { cn } from '@/lib/utils'
import type { BadgeVariant } from '@/types'

interface BadgeProps {
  variant: BadgeVariant
  children: React.ReactNode
  className?: string
}

const variantStyles: Record<BadgeVariant, string> = {
  rush: 'bg-[#FFFBEB] text-[#D97706] border border-[#FDE68A]',
  target: 'bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE]',
  safe: 'bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0]',
  high_rush: 'bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]',
  high: 'bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]',
  medium: 'bg-[#FFFBEB] text-[#D97706] border border-[#FDE68A]',
  low: 'bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0]',
  info: 'bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE]',
}

export default function Badge({ variant, children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded-tag text-xs font-medium',
        variantStyles[variant],
        className
      )}
    >
      {children}
    </span>
  )
}
