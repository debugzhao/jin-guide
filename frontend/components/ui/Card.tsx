import { cn } from '@/lib/utils'
import { HTMLAttributes } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {}

export default function Card({ className, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'wj-card bg-white rounded-card p-4 shadow-sm border border-[#E2E8F0]',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}
