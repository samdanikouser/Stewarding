import { Inbox } from 'lucide-react'
import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-pulse rounded bg-surface-muted', className)} />
}

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className={cn('w-full text-left text-sm [&_tbody_tr:hover]:bg-surface-muted/60 [&_tbody_tr:last-child_td]:border-b-0', className)} {...props} />
    </div>
  )
}

export function Th({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn('border-b border-border bg-surface-muted/70 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-muted', className)} {...props} />
}

export function Td({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('border-b border-border px-4 py-3 align-middle', className)} {...props} />
}

export function SkeletonRows({ cols, rows = 5 }: { cols: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r}>
          {Array.from({ length: cols }, (_, c) => (
            <Td key={c}>
              <Skeleton className="h-4 w-full" />
            </Td>
          ))}
        </tr>
      ))}
    </>
  )
}

export function EmptyState({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-soft"><Inbox className="h-6 w-6 text-brand" aria-hidden /></span>
      <p className="font-medium">{title}</p>
      {action}
    </div>
  )
}
