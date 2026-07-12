'use client'

import { useRouter } from 'next/navigation'
import { ChevronLeft } from 'lucide-react'
import { cn } from '@/lib/utils'

interface TopNavProps {
  title: string
  showBack?: boolean
  backHref?: string
  onBack?: () => void
  rightSlot?: React.ReactNode
  className?: string
}

export default function TopNav({
  title,
  showBack = false,
  backHref,
  onBack,
  rightSlot,
  className,
}: TopNavProps) {
  const router = useRouter()

  const handleBack = () => {
    if (onBack) {
      onBack()
    } else if (backHref) {
      router.push(backHref)
    } else {
      router.back()
    }
  }

  return (
    <nav
      className={cn(
        'wj-topnav',
        'sticky top-0 z-30 bg-white/90 backdrop-blur border-b border-[#E2E8F0]',
        className
      )}
    >
      <div className="wj-topnav-inner flex items-center px-4 h-14">
        {showBack && (
          <button
            onClick={handleBack}
            className="wj-topnav-back mr-2 p-1 -ml-1 text-[#0F172A]"
            aria-label="返回"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
        )}
        <h1 className="wj-topnav-title flex-1 text-base font-semibold text-[#0F172A] truncate">
          {title}
        </h1>
        {rightSlot && <div className="ml-2">{rightSlot}</div>}
      </div>
    </nav>
  )
}
