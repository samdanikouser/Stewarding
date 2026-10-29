import { CircleAlert, CircleCheck, TriangleAlert, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface KpiCardProps {
  label: string
  value: string | number
  tone?: 'default' | 'critical' | 'warn' | 'ok'
  icon?: LucideIcon
}

const TONES = {
  default: 'border-border bg-surface',
  critical: 'border-border border-l-4 border-l-danger bg-surface',
  warn: 'border-border border-l-4 border-l-warn bg-surface',
  ok: 'border-border border-l-4 border-l-ok bg-surface',
}

const TONE_MARK = { critical: [CircleAlert, 'Critical'], warn: [TriangleAlert, 'Needs attention'], ok: [CircleCheck, 'On track'] } as const

const ICON_TONES = {
  default: 'bg-brand-soft text-brand',
  critical: 'bg-danger/10 text-danger',
  warn: 'bg-warn/10 text-warn',
  ok: 'bg-ok/10 text-ok',
}

export function KpiCard({ label, value, tone = 'default', icon: Icon }: KpiCardProps) {
  const [Mark, markText] = tone === 'default' ? [null, ''] : TONE_MARK[tone]
  return (
    <div className={cn('rounded-2xl border p-4 shadow-[0_1px_2px_rgba(27,36,32,0.05),0_8px_24px_-12px_rgba(27,36,32,0.12)]', TONES[tone])}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-ink-muted">{label}</p>
        {Icon && <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-lg', ICON_TONES[tone])}><Icon className="h-4 w-4" aria-hidden /></span>}
      </div>
      <p className={cn('mt-1 flex items-center gap-2 text-3xl font-semibold tabular-nums tracking-tight', tone === 'critical' && 'text-danger', tone === 'warn' && 'text-warn', tone === 'ok' && 'text-ok')}>
        {Mark && <Mark className="h-5 w-5 shrink-0" aria-hidden />}
        {markText && <span className="sr-only">{markText}: </span>}
        {value}
      </p>
    </div>
  )
}
