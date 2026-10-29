import type { InputHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'h-10 w-full rounded-lg border border-border-strong bg-surface pointer-coarse:h-11 px-3 text-sm placeholder:text-ink-muted focus-visible:outline-2 focus-visible:outline-brand',
        className,
      )}
      {...props}
    />
  )
}
