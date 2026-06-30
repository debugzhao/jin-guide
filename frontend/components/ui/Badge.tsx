import { cn } from '@/lib/utils'
import type { BadgeVariant } from '@/types'

interface BadgeProps {
  variant: BadgeVariant
  children: React.ReactNode
  className?: string
}

const variantStyles: Record<BadgeVariant, string> = {
  rush: 'bg-orange-100 text-orange-700',
  target: 'bg-blue-100 text-blue-700',
  safe: 'bg-green-100 text-green-700',
  high_rush: 'bg-red-100 text-red-700',
  high: 'bg-[#FEF2F2] text-[#DC2626]',
  medium: 'bg-[#FFFBEB] text-[#D97706]',
  low: 'bg-[#F0FDF4] text-[#16A34A]',
  info: 'bg-[#EFF6FF] text-[#2563EB]',
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
