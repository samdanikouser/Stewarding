import { CalendarOff, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { LocationSelect } from '@/components/LocationSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { CardGrid, RecordCard } from '@/components/ui/record-card'
import { Select } from '@/components/ui/select'
import { EmptyState } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDate, label, weekdaysText } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { cycleOffset, cycleStart, cycleWeek } from '@/lib/rosterCycle'
import { qs, useApi } from '@/lib/useApi'
import type { EmployeeRow } from '@/pages/EmployeeForm'

interface Today {
  employee_id: number
  name: string
  shift: string
  shift_start: string
  checked_in: boolean
  late_minutes: number
  on_duty: boolean
  elsewhere: string | null
  day_type: 'work' | 'week_off' | 'absence'
  absence_type: string | null
}
interface Shift {
  id: number
  name: string
  start_time: string
  end_time: string
  grace_minutes: number
  kind: 'work' | 'weekoff'
  active: boolean
}
interface Assignment {
  id: number
  employee_id: number
  shift_id: number
  weekday: number
  valid_from: string
  valid_to: string | null
  cycle_weeks: number
  cycle_week: number
}
interface Group {
  key: string
  employee_id: number
  shift_id: number
  valid_from: string
  valid_to: string | null
  weekdays: number[]
  ids: number[]
  cycle_weeks: number
  cycle_week: number
}
interface Draft {
  ids: number[] | null
  employee_id: string
  shift_id: string
  weekdays: number[]
  valid_from: string
  valid_to: string
  cycle_weeks: number
  offset: number
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const PAGE = 12
const BLANK: Draft = { ids: null, employee_id: '', shift_id: '', weekdays: [0, 1, 2, 3, 4], valid_from: '', valid_to: '', cycle_weeks: 1, offset: 0 }

export function RosterPage() {
  const { me } = useAuth()
  const run = useRun()
  const canManage = me?.permissions.includes('roster.manage') ?? false
  const [locationId, setLocationId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [removing, setRemoving] = useState<Group | null>(null)
  const [search, setSearch] = useState('')
  const [shiftFilter, setShiftFilter] = useState('')
  const [shown, setShown] = useState(PAGE)

  const today = useApi<Today[]>(locationId ? `/roster/today${qs({ location_id: locationId })}` : null)
  const shifts = useApi<Shift[]>('/roster/shifts')
  const assignments = useApi<Assignment[]>(`/roster/assignments${qs({ location_id: locationId })}`)
  const people = useApi<{ items: EmployeeRow[] }>(`/employees${qs({ location_id: locationId, status: 'active', size: 200 })}`)
  const names = new Map(people.data?.items.map((e) => [e.id, e.full_name]))
  const shiftById = new Map(shifts.data?.map((s) => [s.id, s]))

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!draft) return
    const shared = {
      shift_id: Number(draft.shift_id), weekdays: draft.weekdays, valid_from: draft.valid_from, valid_to: draft.valid_to || null,
      cycle_weeks: draft.cycle_weeks, cycle_week: cycleWeek(draft.valid_from, draft.cycle_weeks, draft.offset),
    }
    const ok = await run(
      () => draft.ids
        ? api('/roster/assignments', { method: 'PUT', body: { ids: draft.ids, ...shared } })
        : api('/roster/assignments', { body: { employee_id: Number(draft.employee_id), location_id: locationId, ...shared } }),
      draft.ids ? 'Assignment updated' : 'Shift assigned',
    )
    if (ok) {
      setDraft(null)
      assignments.reload()
    }
  }

  async function end(group: Group) {
    if (await run(() => api('/roster/assignments/end', { body: { ids: group.ids } }), 'Assignment ended')) assignments.reload()
  }

  async function remove() {
    if (!removing) return
    const done = await run(() => api('/roster/assignments/remove', { body: { ids: removing.ids } }), 'Assignment deleted')
    setRemoving(null)
    if (done) assignments.reload()
  }

  // one card per employee, shift and period, however many weekdays it covers
  const groups = (() => {
    const out = new Map<string, Group>()
    for (const a of assignments.data ?? []) {
      const key = `${a.employee_id}|${a.shift_id}|${a.valid_from}|${a.valid_to ?? ''}|${a.cycle_weeks}|${a.cycle_week}`
      const group = out.get(key)
      if (group) {
        group.weekdays.push(a.weekday)
        group.ids.push(a.id)
      } else out.set(key, { key, employee_id: a.employee_id, shift_id: a.shift_id, valid_from: a.valid_from, valid_to: a.valid_to, weekdays: [a.weekday], ids: [a.id], cycle_weeks: a.cycle_weeks, cycle_week: a.cycle_week })
    }
    const needle = search.trim().toLowerCase()
    return [...out.values()]
      .map((g) => ({ ...g, weekdays: [...g.weekdays].sort((x, y) => x - y) }))
      .filter((g) => (!shiftFilter || String(g.shift_id) === shiftFilter) && (!needle || (names.get(g.employee_id) ?? '').toLowerCase().includes(needle)))
      .sort((x, y) => (names.get(x.employee_id) ?? '').localeCompare(names.get(y.employee_id) ?? '') || x.valid_from.localeCompare(y.valid_from))
  })()

  const editing = draft?.ids != null
  const toggleDay = (day: number) => setDraft((d) => d && { ...d, weekdays: d.weekdays.includes(day) ? d.weekdays.filter((x) => x !== day) : [...d.weekdays, day].sort() })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Shift &amp; Duty Roster</h1>
        <div className="flex flex-wrap items-center gap-3">
          <LocationSelect allowAll value={locationId} onChange={setLocationId} />
          {canManage && <Button onClick={() => setDraft({ ...BLANK })}><Plus className="h-4 w-4" /> Assign shift</Button>}
        </div>
      </div>

      <Card>
        <CardHeader className="p-6 pb-3"><CardTitle className="text-lg">Scheduled today</CardTitle></CardHeader>
        <CardContent className="p-6 pt-2">
          {!locationId ? <p className="text-sm text-ink-muted">Choose a location to see who is scheduled there today.</p> : today.data?.length === 0 ? <EmptyState title="Nobody is scheduled today" /> : (
            <ul className="divide-y divide-border">
              {today.data?.map((p) => (
                <li key={`${p.employee_id}-${p.shift}`} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                  <span className="font-medium">{p.name}</span>
                  <span className="text-ink-muted">{p.day_type === 'week_off' ? p.shift : `${p.shift} from ${p.shift_start.slice(0, 5)}`}</span>
                  <span className="flex flex-wrap gap-1.5">
                    {p.day_type === 'work' ? (
                      <Badge tone={p.on_duty ? 'ok' : p.checked_in || p.elsewhere ? 'neutral' : 'warn'}>
                        {p.on_duty ? 'On duty' : p.checked_in ? 'Checked out' : p.elsewhere ? `Working at ${p.elsewhere}` : 'Not checked in'}
                      </Badge>
                    ) : p.day_type === 'week_off' ? <Badge>Week off</Badge> : <Badge tone={p.absence_type === 'absent' ? 'critical' : 'neutral'}>{label(p.absence_type ?? 'absent')}</Badge>}
                    {p.late_minutes > 0 && <Badge tone="warn">Late {p.late_minutes}m</Badge>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <section className="space-y-4" aria-label="Weekly assignments">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="mr-auto text-lg font-semibold">Weekly assignments</h2>
          <Input aria-label="Search employees" className="max-w-56" placeholder="Search employee" value={search}
            onChange={(e) => { setSearch(e.target.value); setShown(PAGE) }} />
          <Select aria-label="Shift" className="w-auto" value={shiftFilter} onChange={(e) => { setShiftFilter(e.target.value); setShown(PAGE) }}>
            <option value="">All shifts</option>
            {shifts.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </div>

        {groups.length > 0 && (
          <CardGrid>
            {groups.slice(0, shown).map((g) => {
              const shift = shiftById.get(g.shift_id)
              return (
                <RecordCard
                  key={g.key}
                  title={names.get(g.employee_id) ?? `Employee ${g.employee_id}`}
                  subtitle={shift ? (shift.kind === 'weekoff' ? `${shift.name} (week off)` : `${shift.name}, ${shift.start_time.slice(0, 5)} to ${shift.end_time.slice(0, 5)}`) : undefined}
                  badges={shift?.kind === 'weekoff' ? <Badge>Week off</Badge> : g.valid_to ? <Badge tone="warn">Ends {fmtDate(g.valid_to)}</Badge> : <Badge tone="ok">Ongoing</Badge>}
                  facts={[
                    { label: 'Days', value: weekdaysText(g.weekdays) },
                    { label: 'Repeats', value: g.cycle_weeks === 1 ? 'Every week' : `Every ${g.cycle_weeks} weeks, from the week of ${fmtDate(cycleStart(g.valid_from, g.cycle_weeks, g.cycle_week))}` },
                    { label: 'From', value: fmtDate(g.valid_from) },
                  ]}
                  actions={canManage ? [
                    { label: 'Edit', icon: Pencil, onClick: () => setDraft({ ids: g.ids, employee_id: String(g.employee_id), shift_id: String(g.shift_id), weekdays: g.weekdays, valid_from: g.valid_from, valid_to: g.valid_to ?? '', cycle_weeks: g.cycle_weeks, offset: cycleOffset(g.valid_from, g.cycle_weeks, g.cycle_week) }) },
                    { label: 'End', icon: CalendarOff, onClick: () => end(g), disabled: g.valid_to !== null, title: g.valid_to ? 'Already ends on a set date' : 'Stop this assignment from today' },
                    { label: 'Delete', icon: Trash2, tone: 'danger', onClick: () => setRemoving(g) },
                  ] : []}
                />
              )
            })}
          </CardGrid>
        )}
        {groups.length > shown && <Button variant="outline" onClick={() => setShown((n) => n + PAGE)}>Show more ({groups.length - shown} left)</Button>}
        {assignments.data && groups.length === 0 && <EmptyState title={assignments.data.length === 0 ? 'No assignments' : 'No assignment matches'} />}
      </section>

      <Modal
        open={draft !== null}
        size="lg"
        title={editing ? 'Edit assignment' : 'Assign shift'}
        description={editing ? 'Change the shift, days or dates. The change is checked like a new assignment.' : 'Roster someone on a shift for the days they work.'}
        onClose={() => setDraft(null)}
        footer={<>
          {draft && draft.weekdays.length === 0 && <span className="mr-auto text-sm text-warn">Choose at least one day.</span>}
          <Button type="button" variant="outline" onClick={() => setDraft(null)}>Cancel</Button>
          <Button type="submit" form="assign-form" disabled={!draft || draft.weekdays.length === 0}>{editing ? 'Save changes' : 'Assign shift'}</Button>
        </>}
      >
        {draft && (
          <form id="assign-form" onSubmit={save} className="space-y-6">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Employee">
                <Select required disabled={editing} value={draft.employee_id} onChange={(e) => setDraft({ ...draft, employee_id: e.target.value })}>
                  <option value="">{people.data?.items.length === 0 ? 'No employees' : 'Select'}</option>
                  {people.data?.items.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
                </Select>
              </Field>
              <Field label="Shift">
                <Select required value={draft.shift_id} onChange={(e) => setDraft({ ...draft, shift_id: e.target.value })}>
                  <option value="">Select</option>
                  {shifts.data?.filter((s) => s.active).map((s) => <option key={s.id} value={s.id}>{s.kind === 'weekoff' ? `${s.name} (week off)` : `${s.name} (${s.start_time.slice(0, 5)}-${s.end_time.slice(0, 5)})`}</option>)}
                </Select>
              </Field>
              <Field label="Valid from"><Input required type="date" value={draft.valid_from} onChange={(e) => setDraft({ ...draft, valid_from: e.target.value })} /></Field>
              <Field label="Valid until (optional)"><Input type="date" min={draft.valid_from || undefined} value={draft.valid_to} onChange={(e) => setDraft({ ...draft, valid_to: e.target.value })} /></Field>
            </div>
            <fieldset>
              <legend className="mb-2 text-sm font-medium">Days</legend>
              <div className="flex flex-wrap gap-2">
                {DAYS.map((d, i) => (
                  <label key={d} className={`cursor-pointer rounded-full border px-4 py-1.5 text-sm transition-colors ${draft.weekdays.includes(i) ? 'border-brand bg-brand-soft font-semibold text-brand-deep' : 'border-border hover:bg-surface-muted'}`}>
                    <input type="checkbox" className="sr-only" checked={draft.weekdays.includes(i)} onChange={() => toggleDay(i)} /> {d}
                  </label>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="ghost" onClick={() => setDraft({ ...draft, weekdays: [0, 1, 2, 3, 4] })}>Weekdays</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setDraft({ ...draft, weekdays: [0, 1, 2, 3, 4, 5, 6] })}>Every day</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setDraft({ ...draft, weekdays: [] })}>Clear</Button>
              </div>
            </fieldset>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Repeats">
                <Select value={draft.cycle_weeks} onChange={(e) => setDraft({ ...draft, cycle_weeks: Number(e.target.value), offset: 0 })}>
                  <option value={1}>Every week</option>
                  <option value={2}>Every 2nd week (alternate weeks)</option>
                  <option value={3}>Every 3rd week</option>
                  <option value={4}>Every 4th week</option>
                </Select>
              </Field>
              {draft.cycle_weeks > 1 && (
                <Field label={draft.valid_from ? 'Which weeks' : 'Which weeks (choose the start date first)'}>
                  <Select disabled={!draft.valid_from} value={draft.offset} onChange={(e) => setDraft({ ...draft, offset: Number(e.target.value) })}>
                    {Array.from({ length: draft.cycle_weeks }, (_, offset) => (
                      <option key={offset} value={offset}>
                        {draft.valid_from ? `The week of ${fmtDate(cycleStart(draft.valid_from, draft.cycle_weeks, cycleWeek(draft.valid_from, draft.cycle_weeks, offset)))}, then every ${draft.cycle_weeks} weeks` : `Week ${offset + 1}`}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removing !== null} title="Delete assignment" confirmLabel="Delete assignment"
        message={`Delete the ${removing ? shiftById.get(removing.shift_id)?.name ?? 'shift' : 'shift'} assignment for ${removing ? names.get(removing.employee_id) ?? 'this employee' : 'this employee'}? It is removed completely, as if it had never been made. To stop it from today and keep the record, use End instead.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
