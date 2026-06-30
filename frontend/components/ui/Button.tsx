'use client'

import { cn } from '@/lib/utils'
import { ButtonHTMLAttributes, forwardRef } from 'react'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'outline' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', disabled, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled}
        className={cn(
          'inline-flex items-center justify-center font-medium transition-colors rounded-btn',
          'focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-2',
          disabled && 'opacity-50 cursor-not-allowed',
          variant === 'primary' && [
            'bg-[#1E40AF] text-white',
            !disabled && 'hover:bg-[#1E3A8A] active:bg-[#1E3A8A]',
          ],
          variant === 'outline' && [
            'border border-[#1E40AF] text-[#1E40AF] bg-transparent',
            !disabled && 'hover:bg-blue-50',
          ],
          variant === 'ghost' && [
            'text-[#64748B] bg-transparent',
            !disabled && 'hover:bg-gray-100',
          ],
          size === 'sm' && 'text-sm px-3 py-1.5',
          size === 'md' && 'text-base px-4 py-2.5',
          size === 'lg' && 'text-lg px-6 py-3 w-full',
          className
        )}
        {...props}
      >
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'
export default Button
