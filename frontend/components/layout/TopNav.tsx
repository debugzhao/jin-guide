'use client'

import { useRouter } from 'next/navigation'
import { ChevronLeft } from 'lucide-react'
import { cn } from '@/lib/utils'

interface TopNavProps {
  title: string
  showBack?: boolean
  backHref?: string
  rightSlot?: React.ReactNode
  className?: string
}

export default function TopNav({
  title,
  showBack = false,
  backHref,
  rightSlot,
  className,
}: TopNavProps) {
  const router = useRouter()

  const handleBack = () => {
    if (backHref) {
      router.push(backHref)
    } else {
      router.back()
    }
  }

  return (
    <nav
      className={cn(
        'sticky top-0 z-30 bg-white border-b border-[#E2E8F0]',
        'flex items-center h-14 px-4',
        className
      )}
    >
      {showBack && (
        <button
          onClick={handleBack}
          className="mr-2 p-1 -ml-1 text-[#0F172A]"
          aria-label="返回"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
      )}
      <h1 className="flex-1 text-base font-semibold text-[#0F172A] truncate">
        {title}
      </h1>
      {rightSlot && <div className="ml-2">{rightSlot}</div>}
    </nav>
  )
}
