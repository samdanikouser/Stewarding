import type { SelectHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'h-10 w-full rounded-lg border border-border-strong bg-surface pointer-coarse:h-11 px-3 text-sm focus-visible:outline-2 focus-visible:outline-brand',
        className,
      )}
      {...props}
    />
  )
}
