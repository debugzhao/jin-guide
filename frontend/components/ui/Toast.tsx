'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { CheckCircle, XCircle, AlertTriangle, X } from 'lucide-react'
import { create } from 'zustand'

export type ToastType = 'success' | 'error' | 'warning'

interface ToastProps {
  type: ToastType
  message: string
  duration?: number
  onClose: () => void
}

const typeConfig: Record<ToastType, { icon: React.ComponentType<{ className?: string }>; className: string }> = {
  success: { icon: CheckCircle, className: 'bg-[#F0FDF4] border-[#16A34A] text-[#16A34A]' },
  error: { icon: XCircle, className: 'bg-[#FEF2F2] border-[#DC2626] text-[#DC2626]' },
  warning: { icon: AlertTriangle, className: 'bg-[#FFFBEB] border-[#D97706] text-[#D97706]' },
}

export default function Toast({ type, message, duration = 3000, onClose }: ToastProps) {
  const [visible, setVisible] = useState(true)
  const { icon: Icon, className } = typeConfig[type]

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false)
      setTimeout(onClose, 300)
    }, duration)
    return () => clearTimeout(timer)
  }, [duration, onClose])

  return (
    <div
      className={cn(
        'fixed top-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2',
        'px-4 py-3 rounded-btn border shadow-md transition-opacity duration-300 max-w-xs w-full',
        className,
        !visible && 'opacity-0'
      )}
    >
      <Icon className="w-4 h-4 flex-shrink-0" />
      <span className="text-sm flex-1 text-[#0F172A]">{message}</span>
      <button onClick={() => { setVisible(false); setTimeout(onClose, 300) }} className="ml-1">
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

// Toast manager hook
interface ToastItem {
  id: string
  type: ToastType
  message: string
}

interface ToastStore {
  toasts: ToastItem[]
  addToast: (type: ToastType, message: string) => void
  removeToast: (id: string) => void
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  addToast: (type, message) =>
    set((state) => ({
      toasts: [...state.toasts, { id: Date.now().toString(), type, message }],
    })),
  removeToast: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}))

export function ToastContainer() {
  const { toasts, removeToast } = useToastStore()
  return (
    <>
      {toasts.map((toast) => (
        <Toast
          key={toast.id}
          type={toast.type}
          message={toast.message}
          onClose={() => removeToast(toast.id)}
        />
      ))}
    </>
  )
}
