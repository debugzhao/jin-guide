import { cn } from '@/lib/utils'
import { HTMLAttributes } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {}

export default function Card({ className, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'wj-card wj-glass-card rounded-card p-4',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}
