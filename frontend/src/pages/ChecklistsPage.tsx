import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ScanButton } from '@/components/ScanButton'
import { WorkLocationSelect } from '@/components/WorkLocationSelect'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDate, todayIso, weekRange } from '@/lib/format'
import { useRun, useToast } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { ChecklistConfig } from '@/pages/ChecklistConfig'
import { ChecklistTaskCard, type Instance } from '@/pages/ChecklistTaskCard'
import type { EmployeeRow } from '@/pages/EmployeeForm'

const DONE = ['completed', 'pending_verification', 'verified', 'waived']

export function ChecklistsPage() {
  const { me } = useAuth()
  const run = useRun()
  const toast = useToast()
  const arrived = useLocation().state as { locationId?: number } | null
  const [locationId, setLocationId] = useState<number | null>(arrived?.locationId ?? null)
  const [day, setDay] = useState(todayIso())
  const [view, setView] = useState<'day' | 'week'>('day')
  const [status, setStatus] = useState('')
  const [frequency, setFrequency] = useState('')
  const [configuring, setConfiguring] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const [selecting, setSelecting] = useState(false)
  const [assignee, setAssignee] = useState('')
  const [waiving, setWaiving] = useState(false)
  const [reason, setReason] = useState('')
  const canConfigure = me?.permissions.includes('checklist.configure') ?? false
  const range = weekRange(day)

  const { data, loading, reload } = useApi<{ items: Instance[] }>(
    locationId === null ? null : `/checklists/instances${qs({
      location_id: locationId, status, frequency,
      ...(view === 'week' ? { date_from: range.from, date_to: range.to } : { day }), size: 200,
    })}`,
  )
  const staff = useApi<{ items: EmployeeRow[] }>(me?.permissions.includes('employee.view') ? '/employees?size=200&status=active' : null)
  const items = data?.items ?? []
  const done = items.filter((i) => DONE.includes(i.effective_status)).length
  const percent = items.length ? Math.round((done / items.length) * 100) : 0
  const timezone = me?.locations.find((l) => l.id === locationId)?.timezone
  const approvable = me?.permissions.includes('checklist.verify') ? items.filter((i) => i.effective_status === 'pending_verification' && i.completed_by !== me.id) : []
  const days = [...new Set(items.map((i) => i.local_date))].sort()
  const canAssign = me?.permissions.includes('task.assign') ?? false
  const canWaive = me?.permissions.includes('checklist.verify') ?? false
  const selectable = items.filter((i) => !['verified', 'waived'].includes(i.effective_status)).map((i) => i.id)
  const people = (staff.data?.items ?? []).filter((e) => e.location_ids.includes(locationId ?? -1))
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))

  async function afterBulk(path: string, body: Record<string, unknown>, done: (r: Record<string, number>) => string) {
    try {
      toast('ok', done(await api<Record<string, number>>(`/checklists/instances/${path}`, { body })))
    } catch (err) {
      toast('error', err instanceof Error ? err.message : 'Something went wrong')
      return
    }
    setSelected([])
    setWaiving(false)
    setReason('')
    reload()
  }

  async function approveAll() {
    const ids = approvable.map((i) => i.id)
    const result = await run(() => api('/checklists/instances/verify-many', { body: { instance_ids: ids } }), `${ids.length} task${ids.length === 1 ? '' : 's'} approved`)
    if (result) reload()
  }

  const cards = (list: Instance[]) => (
    <div className="grid gap-3 lg:grid-cols-2">
      {list.map((i) => (
        <ChecklistTaskCard key={i.id} item={i} timezone={timezone} staff={staff.data?.items ?? []} onChanged={reload}
          selection={selecting && selectable.includes(i.id) ? { checked: selected.includes(i.id), onToggle: () => toggle(i.id) } : undefined} />
      ))}
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Checklists</h1>
        <div className="flex flex-wrap items-center gap-3">
          {me?.permissions.includes('checklist.complete') && <ScanButton />}
          {canConfigure && <Button variant="outline" onClick={() => setConfiguring((c) => !c)}>{configuring ? 'Back to tasks' : 'Configure'}</Button>}
        </div>
      </div>

      {configuring ? <ChecklistConfig locationId={locationId} onLocation={setLocationId} /> : (
        <>
          <div className="filter-bar">
            <WorkLocationSelect value={locationId} onChange={setLocationId} />
            <div role="group" aria-label="View" className="inline-flex rounded-lg border border-border bg-surface p-0.5">
              {(['day', 'week'] as const).map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
                  className={cn('rounded-md px-3 py-1.5 text-sm font-medium', view === v ? 'bg-brand text-brand-ink' : 'text-ink-muted hover:text-ink')}>
                  {v === 'day' ? 'Day' : 'Week'}
                </button>
              ))}
            </div>
            <Input aria-label="Date" type="date" className="w-auto" value={day} onChange={(e) => setDay(e.target.value)} />
            <Select aria-label="Frequency filter" className="w-auto" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
              <option value="">Every frequency</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="per_shift">Once per shift</option>
              <option value="custom">Custom</option>
            </Select>
            <Select aria-label="Status filter" className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              <option value="not_started">Not started</option>
              <option value="in_progress">In progress</option>
              <option value="pending_verification">Pending verification</option>
              <option value="completed">Completed</option>
              <option value="verified">Verified</option>
              <option value="failed">Failed</option>
              <option value="overdue">Overdue</option>
              <option value="waived">Waived</option>
            </Select>
          </div>

          <div aria-label="Completion progress">
            <div className="mb-1 flex justify-between text-sm"><span>{done} of {items.length} done</span><span>{percent}%</span></div>
            <div className="h-2 overflow-hidden rounded bg-border"><div className="h-full bg-brand" style={{ width: `${percent}%` }} /></div>
          </div>

          {(canAssign || canWaive) && items.length > 0 && (
            <div className="flex flex-wrap items-end gap-3 rounded-md border border-border bg-surface px-3 py-2 text-sm">
              <Button size="sm" variant={selecting ? 'default' : 'outline'} onClick={() => { setSelecting((s) => !s); setSelected([]) }}>{selecting ? 'Done selecting' : 'Select tasks'}</Button>
              {selecting && (
                <>
                  <Button size="sm" variant="outline" onClick={() => setSelected(selectable)}>Select all ({selectable.length})</Button>
                  <span className="py-1.5 text-ink-muted">{selected.length} selected</span>
                  {canAssign && (
                    <>
                      <Select aria-label="Assign to" className="h-8 w-48" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                        <option value="">Assign to...</option>
                        {people.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
                      </Select>
                      <Button size="sm" disabled={selected.length === 0 || !assignee}
                        onClick={() => afterBulk('assign-many', { instance_ids: selected, employee_id: Number(assignee) }, (r) => `${r.assigned} assigned${r.skipped ? `, ${r.skipped} skipped` : ''}`)}>Assign</Button>
                    </>
                  )}
                  {canWaive && <Button size="sm" variant="outline" disabled={selected.length === 0} onClick={() => setWaiving(true)}>Waive...</Button>}
                </>
              )}
            </div>
          )}
          {approvable.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-surface px-3 py-2 text-sm">
              <span>{approvable.length} task{approvable.length === 1 ? '' : 's'} awaiting your approval</span>
              <Button size="sm" onClick={approveAll}>Approve all ({approvable.length})</Button>
            </div>
          )}
          {loading && !data ? <Skeleton className="h-32 w-full" /> : items.length === 0 ? (
            <EmptyState title="No tasks for this selection" />
          ) : view === 'week' ? (
            <div className="space-y-5">
              {days.map((d) => (
                <section key={d} aria-label={fmtDate(d)} className="space-y-2">
                  <h2 className="text-sm font-semibold text-ink-muted">{new Intl.DateTimeFormat('en-GB', { weekday: 'long', timeZone: 'UTC' }).format(new Date(`${d}T00:00:00Z`))}, {fmtDate(d)}</h2>
                  {cards(items.filter((i) => i.local_date === d))}
                </section>
              ))}
            </div>
          ) : cards(items)}
        </>
      )}
      <Modal
        open={waiving}
        size="md"
        title={`Waive ${selected.length} task${selected.length === 1 ? '' : 's'}`}
        description="Waived tasks count as done. The reason is kept with each one."
        onClose={() => setWaiving(false)}
        footer={<>
          <Button variant="outline" onClick={() => setWaiving(false)}>Cancel</Button>
          <Button variant="danger" disabled={reason.trim().length < 5}
            onClick={() => afterBulk('waive-many', { instance_ids: selected, reason: reason.trim() }, (r) => `${r.waived} waived${r.skipped ? `, ${r.skipped} skipped` : ''}`)}>Waive</Button>
        </>}
      >
        <Field label="Reason"><Input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
    </div>
  )
}
