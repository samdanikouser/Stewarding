import { ChevronRight, Clock } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { useAuth } from '@/lib/auth'
import { fmtDate, fmtTime, hoursMinutes } from '@/lib/format'
import { useApi } from '@/lib/useApi'
import { MyShiftCard } from '@/pages/MyShiftCard'

interface Day {
  id: number
  local_date: string
  check_in_at: string
  check_out_at: string | null
  late_minutes: number
  payable_minutes: number | null
  open: boolean
  missed_checkout: boolean
}

/** What time it is now, refreshed every half minute, for the header of the check-in screen. */
function useNow() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(timer)
  }, [])
  return now
}

/** The screen people open on their phone to check in and out, with their last few days beneath. */
export function CheckInPage() {
  const now = useNow()
  const { me } = useAuth()
  const recent = useApi<{ items: Day[] }>('/attendance/mine?size=7')

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Check in &amp; out</h1>
        <p className="flex items-center gap-2 text-ink-muted">
          <Clock aria-hidden className="h-4 w-4" />
          <span className="text-lg font-semibold tabular-nums text-ink">{new Intl.DateTimeFormat('en-GB', { timeStyle: 'short' }).format(now)}</span>
          <span>{new Intl.DateTimeFormat('en-GB', { dateStyle: 'full' }).format(now)}</span>
        </p>
      </header>

      <MyShiftCard onChange={recent.reload} />
      {me?.permissions.includes('settings.manage') && (
        <p className="text-sm">
          <Link to="/settings/attendance" className="font-medium text-brand-deep hover:underline">Check-in rules</Link>
          <span className="text-ink-muted"> - face check, location accuracy and missed check-out</span>
        </p>
      )}

      <section className="space-y-3" aria-label="Recent days">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Your last days</h2>
          <Link to="/attendance" className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-brand-deep hover:underline">
            All attendance and leave <ChevronRight aria-hidden className="h-4 w-4" />
          </Link>
        </div>
        {!recent.data ? <Skeleton className="h-24 w-full" /> : recent.data.items.length === 0 ? <EmptyState title="No attendance yet" /> : (
          <ul className="space-y-3">
            {recent.data.items.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-surface px-5 py-4">
                <div>
                  <p className="font-medium">{fmtDate(d.local_date)}</p>
                  <p className="text-sm text-ink-muted">{fmtTime(d.check_in_at)} to {d.open ? 'on duty' : fmtTime(d.check_out_at)}</p>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {d.late_minutes > 0 && <Badge tone="warn">Late {d.late_minutes}m</Badge>}
                  {d.missed_checkout && <Badge tone="critical">Missed checkout</Badge>}
                  <span className="text-sm font-semibold tabular-nums">{d.open ? 'Now' : hoursMinutes(d.payable_minutes)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
