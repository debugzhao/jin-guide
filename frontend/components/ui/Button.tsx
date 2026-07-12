'use client'

import Link from 'next/link'
import { cn } from '@/lib/utils'
import { ButtonHTMLAttributes, forwardRef } from 'react'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'outline' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  href?: string
}

const buttonClassName = ({
  className,
  variant = 'primary',
  size = 'md',
  disabled,
}: Pick<ButtonProps, 'className' | 'variant' | 'size' | 'disabled'>) =>
  cn(
    'wj-button',
    `wj-button-${variant}`,
    `wj-button-${size}`,
    'inline-flex items-center justify-center font-medium transition-colors rounded-btn',
    'focus:outline-none focus:ring-2 focus:ring-[#1E40AF]/30 focus:ring-offset-0',
    disabled && 'opacity-50 cursor-not-allowed',
    variant === 'primary' && [
      'bg-[#1E40AF] text-white',
      !disabled && 'hover:bg-[#1E3A8A] active:bg-[#1E3A8A]',
    ],
    variant === 'outline' && [
      'border border-[#E2E8F0] text-[#0F172A] bg-transparent',
      !disabled && 'hover:border-[#1E40AF]/40 hover:bg-[#F8FAFC]',
    ],
    variant === 'ghost' && [
      'text-[#64748B] bg-transparent',
      !disabled && 'hover:bg-[#F1F5F9] hover:text-[#0F172A]',
    ],
    size === 'sm' && 'text-sm px-3 py-1.5',
    size === 'md' && 'text-base px-4 py-2.5',
    size === 'lg' && 'text-lg px-6 py-3 w-full',
    className
  )

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', disabled, children, href, ...props }, ref) => {
    const classes = buttonClassName({ className, variant, size, disabled })

    if (href && !disabled) {
      return (
        <Link href={href} className={classes}>
          {children}
        </Link>
      )
    }

    return (
      <button
        ref={ref}
        disabled={disabled}
        className={classes}
        {...props}
      >
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'
export default Button
