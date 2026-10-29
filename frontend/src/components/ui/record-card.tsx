import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export interface CardAction {
  label: string
  onClick: () => void
  icon?: LucideIcon
  tone?: 'danger'
  disabled?: boolean
  title?: string
}

interface RecordCardProps {
  title: string
  subtitle?: string
  badges?: ReactNode
  facts?: { label: string; value: ReactNode }[]
  actions: CardAction[]
  inactive?: boolean
  children?: ReactNode
  media?: ReactNode
}

/** One record of a settings list: what it is, a few facts, and everything that can be done with it. */
export function RecordCard({ title, subtitle, badges, facts, actions, inactive, children, media }: RecordCardProps) {
  return (
    <Card className={cn('flex flex-col transition-shadow hover:shadow-md', inactive && 'bg-surface-muted/60')}>
      <div className="flex-1 space-y-4 p-5">
        <div className="flex items-start justify-between gap-3">
          {media}
          <div className="min-w-0 flex-1">
            <h3 className={cn('truncate text-base font-semibold', inactive && 'text-ink-muted')}>{title}</h3>
            {subtitle && <p className="mt-0.5 truncate text-sm text-ink-muted">{subtitle}</p>}
          </div>
          {badges && <div className="flex shrink-0 flex-wrap justify-end gap-1.5">{badges}</div>}
        </div>
        {facts && facts.length > 0 && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
            {facts.map((fact) => (
              <div key={fact.label} className="min-w-0">
                <dt className="text-xs text-ink-muted">{fact.label}</dt>
                <dd className="mt-0.5 break-words text-sm">{fact.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {children}
      </div>
      <div className="flex flex-wrap gap-2 border-t border-border px-5 py-3">
        {actions.map(({ label, onClick, icon: Icon, tone, disabled, title: hint }) => (
          <Button
            key={label}
            size="sm"
            variant="outline"
            disabled={disabled}
            title={hint}
            onClick={onClick}
            className={cn(tone === 'danger' && 'ml-auto border-danger/40 text-danger hover:bg-danger-soft')}
          >
            {Icon && <Icon aria-hidden className="h-3.5 w-3.5" />} {label}
          </Button>
        ))}
      </div>
    </Card>
  )
}

export function CardGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{children}</div>
}

/** The title of a settings list with how many records it holds and the one thing most people come to do. */
export function SectionHeader({ title, count, action }: { title: string; count?: number; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-baseline gap-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        {count !== undefined && <span className="text-sm text-ink-muted">{count}</span>}
      </div>
      {action}
    </div>
  )
}
