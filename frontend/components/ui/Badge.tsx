import { cn } from '@/lib/utils'
import type { BadgeVariant } from '@/types'

interface BadgeProps {
  variant: BadgeVariant
  children: React.ReactNode
  className?: string
}

const variantStyles: Record<BadgeVariant, string> = {
  rush: 'bg-[rgba(239,196,138,0.12)] text-[#EFC48A] border border-[rgba(239,196,138,0.32)]',
  target: 'bg-[rgba(169,180,245,0.12)] text-[#A9B4F5] border border-[rgba(169,180,245,0.32)]',
  safe: 'bg-[rgba(143,224,183,0.12)] text-[#8FE0B7] border border-[rgba(143,224,183,0.32)]',
  high_rush: 'bg-[rgba(242,169,169,0.12)] text-[#F2A9A9] border border-[rgba(242,169,169,0.32)]',
  high: 'bg-[rgba(242,169,169,0.12)] text-[#F2A9A9] border border-[rgba(242,169,169,0.32)]',
  medium: 'bg-[rgba(239,196,138,0.12)] text-[#EFC48A] border border-[rgba(239,196,138,0.32)]',
  low: 'bg-[rgba(143,224,183,0.12)] text-[#8FE0B7] border border-[rgba(143,224,183,0.32)]',
  info: 'bg-[rgba(169,180,245,0.12)] text-[#A9B4F5] border border-[rgba(169,180,245,0.32)]',
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
