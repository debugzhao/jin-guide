import { cn } from '@/lib/utils'

interface SkeletonProps {
  variant?: 'card' | 'text' | 'progress'
  className?: string
}

export default function Skeleton({ variant = 'text', className }: SkeletonProps) {
  if (variant === 'card') {
    return (
      <div className={cn('rounded-card bg-gray-200 animate-pulse', className)}>
        <div className="p-4 space-y-3">
          <div className="h-4 bg-gray-300 rounded w-3/4" />
          <div className="h-3 bg-gray-300 rounded w-1/2" />
          <div className="h-3 bg-gray-300 rounded w-2/3" />
        </div>
      </div>
    )
  }

  if (variant === 'progress') {
    return (
      <div className={cn('h-2 bg-gray-200 rounded-full animate-pulse', className)} />
    )
  }

  return (
    <div
      className={cn('h-4 bg-gray-200 rounded animate-pulse', className)}
    />
  )
}
