import { cn } from '@/lib/utils'
import Button from './Button'
import { FileX } from 'lucide-react'

interface EmptyStateProps {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  actionLabel?: string
  onAction?: () => void
  className?: string
}

export default function EmptyState({
  icon: Icon = FileX,
  title,
  description,
  actionLabel,
  onAction,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center py-16 px-4 text-center',
        className
      )}
    >
      <div className="w-16 h-16 rounded-full bg-[#EFF6FF] flex items-center justify-center mb-4">
        <Icon className="w-8 h-8 text-[#2563EB]" />
      </div>
      <h3 className="text-base font-semibold text-[#0F172A] mb-2">{title}</h3>
      {description && (
        <p className="text-sm text-[#64748B] mb-6">{description}</p>
      )}
      {actionLabel && onAction && (
        <Button variant="primary" size="md" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  )
}
