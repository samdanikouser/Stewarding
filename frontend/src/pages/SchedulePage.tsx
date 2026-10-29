import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { fmtDate, fmtTime } from '@/lib/format'
import { qs, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

interface Shift { name: string; start: string; end: string; week_off: boolean; location: string }
interface Punch { check_in_at: string; check_out_at: string | null; late_minutes: number; open: boolean }
type Outcome = 'worked' | 'late' | 'on_duty' | 'missed'
interface Day { date: string; shifts: Shift[]; leave: string | null; worked: Punch[]; outcome: Outcome | null }
interface Month { month: string; today: string; days: Day[] }

const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const LEAVE: Record<string, string> = {
  absent: 'Absent', day_off: 'Day off', sick_leave: 'Sick leave', annual_leave: 'Annual leave', unpaid_leave: 'Unpaid leave', other_leave: 'Leave',
}

type Kind = 'morning' | 'day' | 'night' | 'off' | 'leave'

/** What a day looks like: a week off or leave first, otherwise by when the first shift starts. */
function kindOf(day: Day): Kind | null {
  if (day.leave) return day.leave === 'day_off' ? 'off' : 'leave'
  const work = day.shifts.find((s) => !s.week_off)
  if (!work) return day.shifts.length ? 'off' : null
  const start = Number(work.start.slice(0, 2))
  if (start >= 20 || work.end <= work.start) return 'night'
  return start < 12 ? 'morning' : 'day'
}

const TONE: Record<Kind, string> = {
  morning: 'bg-warn-soft text-ink',
  day: 'bg-brand-soft text-brand-deep',
  night: 'bg-brand text-white',
  off: 'bg-surface-muted text-ink-muted',
  leave: 'bg-danger-soft text-danger-ink',
}

const OUTCOME: Record<Outcome, { text: string; dot: string }> = {
  worked: { text: 'Worked', dot: 'bg-ok' },
  late: { text: 'Worked, arrived late', dot: 'bg-warn' },
  on_duty: { text: 'On duty', dot: 'bg-brand' },
  missed: { text: 'No check-in recorded', dot: 'bg-danger' },
}

const punches = (d: Day) => d.worked.map((w) => `${fmtTime(w.check_in_at)} - ${w.open ? 'on duty' : fmtTime(w.check_out_at)}${w.late_minutes ? ` (${w.late_minutes} min late)` : ''}`).join(', ')

const labelOf = (day: Day): string => (day.leave ? LEAVE[day.leave] ?? 'Leave' : day.shifts.map((s) => (s.week_off ? 'Week off' : s.name)).join(', '))

const shiftMonth = (month: string, by: number) => {
  const [y, m] = month.split('-').map(Number)
  const next = new Date(y, m - 1 + by, 1)
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`
}

/** A person's own roster for the month, as a colour-coded calendar or a list, for use on a phone. */
export function SchedulePage() {
  const [month, setMonth] = useState<string | null>(null)
  const [view, setView] = useState<'calendar' | 'list'>('calendar')
  const [picked, setPicked] = useState<string | null>(null)
  const { data, error } = useApi<Month>(`/attendance/me/schedule${qs({ month })}`)

  const shown = data?.month ?? month
  const title = shown ? new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric' }).format(new Date(`${shown}-01T12:00:00`)) : ''
  const lead = data ? new Date(`${data.days[0].date}T12:00:00`).getDay() : 0  // the week starts on Sunday
  const chosen = data?.days.find((d) => d.date === (picked ?? data.today)) ?? null
  const busy = data?.days.filter((d) => labelOf(d)) ?? []

  return (
    <div className="mx-auto max-w-md space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">My shift schedule</h1>
        <p className="text-sm text-ink-muted">Your rostered shifts, week offs and leave.</p>
      </header>

      <div role="tablist" aria-label="View" className="grid grid-cols-2 rounded-xl bg-surface-muted p-1 text-sm font-medium">
        {(['calendar', 'list'] as const).map((v) => (
          <button key={v} role="tab" aria-selected={view === v} type="button" onClick={() => setView(v)}
            className={cn('min-h-11 rounded-lg transition-colors', view === v ? 'bg-surface shadow-sm' : 'text-ink-muted')}>
            {v === 'calendar' ? 'Calendar' : 'List view'}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <button type="button" aria-label="Previous month" className="grid h-11 w-11 place-items-center rounded-lg hover:bg-surface-muted" disabled={!shown}
          onClick={() => shown && (setMonth(shiftMonth(shown, -1)), setPicked(null))}><ChevronLeft className="h-5 w-5" /></button>
        <h2 className="text-lg font-semibold">{title}</h2>
        <button type="button" aria-label="Next month" className="grid h-11 w-11 place-items-center rounded-lg hover:bg-surface-muted" disabled={!shown}
          onClick={() => shown && (setMonth(shiftMonth(shown, 1)), setPicked(null))}><ChevronRight className="h-5 w-5" /></button>
      </div>

      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : !data ? <Skeleton className="h-72 w-full" /> : view === 'calendar' ? (
        <>
          <div className="grid grid-cols-7 gap-1.5 text-center text-xs text-ink-muted" aria-hidden>{WEEKDAYS.map((d, i) => <span key={i}>{d}</span>)}</div>
          <ul className="grid grid-cols-7 gap-1.5">
            {Array.from({ length: lead }, (_, i) => <li key={`blank-${i}`} aria-hidden />)}
            {data.days.map((d) => {
              const kind = kindOf(d)
              return (
                <li key={d.date}>
                  <button type="button" aria-label={`${fmtDate(d.date)}${labelOf(d) ? `, ${labelOf(d)}` : ''}${d.outcome ? `, ${OUTCOME[d.outcome].text}` : ''}`} aria-pressed={chosen?.date === d.date}
                    onClick={() => setPicked(d.date)}
                    className={cn('grid h-11 w-full place-items-center rounded-lg text-sm font-medium tabular-nums', kind ? TONE[kind] : 'text-ink-muted',
                      d.date === data.today && 'ring-2 ring-brand', chosen?.date === d.date && 'outline outline-2 outline-offset-1 outline-ink')}>
                    <span className="relative">{Number(d.date.slice(8))}{d.outcome && <span aria-hidden className={cn('absolute -bottom-1.5 left-1/2 h-1.5 w-1.5 -translate-x-1/2 rounded-full', OUTCOME[d.outcome].dot)} />}</span>
                  </button>
                </li>
              )
            })}
          </ul>
          <ul className="flex flex-wrap gap-3 text-xs text-ink-muted" aria-label="Key">
            {([['morning', 'Morning'], ['day', 'Afternoon'], ['night', 'Night'], ['off', 'Week off'], ['leave', 'Leave']] as const).map(([k, label]) => (
              <li key={k} className="flex items-center gap-1.5"><span className={cn('inline-block h-3 w-3 rounded', TONE[k])} />{label}</li>
            ))}
          </ul>
          <ul className="flex flex-wrap gap-3 text-xs text-ink-muted" aria-label="What happened">
            {(Object.keys(OUTCOME) as Outcome[]).map((k) => <li key={k} className="flex items-center gap-1.5"><span className={cn('inline-block h-2 w-2 rounded-full', OUTCOME[k].dot)} />{OUTCOME[k].text}</li>)}
          </ul>
          {chosen && (
            <section aria-label="Selected day" className="space-y-1 rounded-xl border border-border bg-surface p-4">
              <p className="font-semibold">{fmtDate(chosen.date)}</p>
              {chosen.leave && <p className="text-sm">{LEAVE[chosen.leave] ?? 'Leave'}</p>}
              {chosen.shifts.map((s) => (
                <p key={`${s.name}-${s.start}`} className="text-sm text-ink-muted">
                  {s.week_off ? 'Week off' : <><span className="font-medium text-ink">{s.name}</span>, {s.start} to {s.end}</>}{s.location ? ` at ${s.location}` : ''}
                </p>
              ))}
              {chosen.outcome && <p className="text-sm font-medium">{OUTCOME[chosen.outcome].text}{chosen.worked.length > 0 && <span className="font-normal text-ink-muted">: {punches(chosen)}</span>}</p>}
              {!chosen.leave && chosen.shifts.length === 0 && <p className="text-sm text-ink-muted">Nothing is scheduled.</p>}
            </section>
          )}
        </>
      ) : busy.length === 0 ? <EmptyState title="Nothing is scheduled this month" /> : (
        <ul className="divide-y divide-border rounded-xl border border-border bg-surface">
          {busy.map((d) => {
            const kind = kindOf(d) ?? 'off'
            const time = d.leave ? '' : d.shifts.filter((s) => !s.week_off).map((s) => `${s.start} - ${s.end}`).join(', ')
            return (
              <li key={d.date} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                <span><span className="block font-medium">{fmtDate(d.date)}</span>{time && <span className="text-xs text-ink-muted">{time}</span>}</span>
                <span className="flex flex-col items-end gap-1">
                  <span className={cn('rounded-md px-2.5 py-1 text-xs font-medium', TONE[kind])}>{labelOf(d)}</span>
                  {d.outcome && <span className="flex items-center gap-1.5 text-xs text-ink-muted"><span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', OUTCOME[d.outcome].dot)} />{OUTCOME[d.outcome].text}</span>}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
