import { Copy, Pencil, Plus, Power, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { CardGrid, RecordCard, SectionHeader } from '@/components/ui/record-card'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface Shift {
  id: number
  kind: 'work' | 'weekoff'
  name: string
  start_time: string
  end_time: string
  grace_minutes: number
  break_minutes: number
  overtime_after_minutes: number | null
  active: boolean
}

interface Draft {
  id: number | null
  kind: 'work' | 'weekoff'
  name: string
  start: string
  end: string
  grace: string
  brk: string
  overtime: string
}

const hhmm = (t: string) => t.slice(0, 5)
const BLANK: Draft = { id: null, kind: 'work', name: '', start: '06:00', end: '14:00', grace: '10', brk: '0', overtime: '' }

/** How long a shift runs, counting past midnight; empty when the times are not set. */
function lengthOf(start: string, end: string): string {
  if (!start || !end) return ''
  const [sh, sm] = start.split(':').map(Number)
  const [eh, em] = end.split(':').map(Number)
  const minutes = (eh * 60 + em - (sh * 60 + sm) + 1440) % 1440
  return `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ''}${eh * 60 + em <= sh * 60 + sm ? ', ends the next day' : ''}`
}

const KINDS: { value: Draft['kind']; title: string }[] = [
  { value: 'work', title: 'Working shift' },
  { value: 'weekoff', title: 'Week off' },
]

export function SettingsShifts() {
  const run = useRun()
  const { data, reload } = useApi<Shift[]>('/roster/shifts')
  const [form, setForm] = useState<Draft | null>(null)
  const [removing, setRemoving] = useState<Shift | null>(null)

  const draftOf = (s: Shift, copy: boolean): Draft => ({
    id: copy ? null : s.id, kind: s.kind, name: copy ? `${s.name} copy` : s.name, start: hhmm(s.start_time), end: hhmm(s.end_time),
    grace: String(s.grace_minutes), brk: String(s.break_minutes), overtime: s.overtime_after_minutes == null ? '' : String(s.overtime_after_minutes),
  })

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!form) return
    const body = {
      kind: form.kind, name: form.name, start_time: `${form.start}:00`, end_time: `${form.end}:00`, grace_minutes: Number(form.grace),
      break_minutes: Number(form.brk), overtime_after_minutes: form.overtime === '' ? null : Number(form.overtime), active: true,
    }
    const ok = await run(() => form.id ? api(`/roster/shifts/${form.id}`, { method: 'PUT', body }) : api('/roster/shifts', { body }), form.id ? 'Shift updated' : 'Shift added')
    if (ok) {
      setForm(null)
      reload()
    }
  }

  async function setActive(shift: Shift) {
    const body = { kind: shift.kind, name: shift.name, start_time: shift.start_time, end_time: shift.end_time, grace_minutes: shift.grace_minutes,
      break_minutes: shift.break_minutes, overtime_after_minutes: shift.overtime_after_minutes, active: !shift.active }
    if (await run(() => api(`/roster/shifts/${shift.id}`, { method: 'PUT', body }), shift.active ? 'Shift made inactive' : 'Shift made active')) reload()
  }

  async function remove() {
    if (!removing) return
    const done = await run(() => api(`/roster/shifts/${removing.id}`, { method: 'DELETE' }), 'Shift deleted')
    setRemoving(null)
    if (done) reload()
  }

  if (!data) return <Skeleton className="h-48 w-full" />
  return (
    <div className="space-y-6">
      <SectionHeader title="Shifts" count={data.length} action={<Button onClick={() => setForm(BLANK)}><Plus className="h-4 w-4" /> Add shift</Button>} />

      {data.length === 0 ? <EmptyState title="No shifts yet" /> : (
        <CardGrid>
          {data.map((s) => (
            <RecordCard
              key={s.id}
              title={s.name}
              subtitle={s.kind === 'weekoff' ? 'Day off, not scheduled and not chased for check-in' : `${hhmm(s.start_time)} to ${hhmm(s.end_time)} (${lengthOf(hhmm(s.start_time), hhmm(s.end_time))})`}
              inactive={!s.active}
              badges={<>{s.kind === 'weekoff' && <Badge>Week off</Badge>}<Badge tone={s.active ? 'ok' : 'neutral'}>{s.active ? 'Active' : 'Inactive'}</Badge></>}
              facts={s.kind === 'weekoff' ? [] : [
                { label: 'Late after', value: `${s.grace_minutes} min` },
                { label: 'Break', value: `${s.break_minutes} min` },
                { label: 'Overtime after', value: s.overtime_after_minutes == null ? 'Shift length' : `${s.overtime_after_minutes} min` },
              ]}
              actions={[
                { label: 'Edit', icon: Pencil, onClick: () => setForm(draftOf(s, false)) },
                { label: 'Copy', icon: Copy, onClick: () => setForm(draftOf(s, true)) },
                { label: s.active ? 'Make inactive' : 'Make active', icon: Power, onClick: () => setActive(s) },
                { label: 'Delete', icon: Trash2, tone: 'danger', onClick: () => setRemoving(s) },
              ]}
            />
          ))}
        </CardGrid>
      )}

      <Modal
        open={form !== null}
        title={form?.id ? 'Edit shift' : 'Add shift'}
        description="The hours people are rostered for, and when they count as late or on overtime."
        size="lg"
        onClose={() => setForm(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setForm(null)}>Cancel</Button>
          <Button type="submit" form="shift-form">{form?.id ? 'Save shift' : 'Add shift'}</Button>
        </>}
      >
        {form && (
          <form id="shift-form" onSubmit={save} className="space-y-6">
            <div role="radiogroup" aria-label="Type" className="grid grid-cols-2 gap-3">
              {KINDS.map((k) => (
                <button key={k.value} type="button" role="radio" aria-checked={form.kind === k.value} disabled={form.id !== null && form.kind !== k.value}
                  onClick={() => setForm({ ...form, kind: k.value })}
                  className={cn('rounded-xl border px-4 py-3 text-left text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                    form.kind === k.value ? 'border-brand bg-brand-soft text-brand-deep ring-1 ring-brand/40' : 'border-border bg-surface hover:bg-surface-muted')}>
                  {k.title}
                </button>
              ))}
            </div>

            <Field label="Name"><Input required maxLength={60} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>

            {form.kind === 'work' && (
              <>
                <div className="space-y-2">
                  <div className="grid gap-5 sm:grid-cols-2">
                    <Field label="Starts"><Input required type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></Field>
                    <Field label="Ends"><Input required type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} /></Field>
                  </div>
                  <p className="text-sm text-ink-muted">Length: {lengthOf(form.start, form.end) || '-'}</p>
                </div>
                <div className="grid gap-5 sm:grid-cols-3">
                  <Field label="Late after (minutes)"><Input type="number" min={0} max={120} value={form.grace} onChange={(e) => setForm({ ...form, grace: e.target.value })} /></Field>
                  <Field label="Break (minutes)"><Input type="number" min={0} max={240} value={form.brk} onChange={(e) => setForm({ ...form, brk: e.target.value })} /></Field>
                  <Field label="Overtime after (minutes)"><Input type="number" min={0} placeholder="Shift length" value={form.overtime} onChange={(e) => setForm({ ...form, overtime: e.target.value })} /></Field>
                </div>
              </>
            )}
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removing !== null} title="Delete shift" confirmLabel="Delete shift"
        message={`Delete ${removing?.name ?? 'this shift'}? This cannot be undone. A shift that the roster, attendance or checklists already use cannot be deleted; make it inactive instead.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
