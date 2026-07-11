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
    'focus:outline-none focus:ring-2 focus:ring-[#A78BFA]/40 focus:ring-offset-0',
    disabled && 'opacity-50 cursor-not-allowed',
    variant === 'primary' && [
      'bg-[#A78BFA] text-white',
      !disabled && 'hover:bg-[#9370F5] active:bg-[#8560E8]',
    ],
    variant === 'outline' && [
      'border border-white/15 text-[#F1F5F9] bg-transparent',
      !disabled && 'hover:border-[#A78BFA]/50 hover:bg-white/[0.03]',
    ],
    variant === 'ghost' && [
      'text-[#9CA3C4] bg-transparent',
      !disabled && 'hover:bg-white/[0.05] hover:text-[#F1F5F9]',
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
