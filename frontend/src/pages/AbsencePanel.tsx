import { Ban, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { LocationSelect } from '@/components/LocationSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { EmptyState } from '@/components/ui/table'
import { api } from '@/lib/api'
import { fmtDate, label } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { useAuth } from '@/lib/auth'

const ABSENCE_TYPES = ['absent', 'day_off', 'sick_leave', 'annual_leave', 'unpaid_leave', 'other_leave']

interface Absence {
  id: number
  employee_name: string
  local_date: string
  absence_type: string
  note: string | null
  status: 'active' | 'void'
  void_reason: string | null
}

const today = () => new Date().toISOString().slice(0, 10)

export function AbsencePanel({ canRecord = true }: { canRecord?: boolean }) {
  const run = useRun()
  const { me } = useAuth()
  const byLocation = me?.by_location !== false  // when attendance is not by location, no outlet is asked for
  const [open, setOpen] = useState(false)
  const [cancelling, setCancelling] = useState<Absence | null>(null)
  const [cancelReason, setCancelReason] = useState('')
  const [locationId, setLocationId] = useState<number | null>(null)
  const [employeeId, setEmployeeId] = useState('')
  const [day, setDay] = useState(today)
  const [dayTo, setDayTo] = useState('')
  const [kind, setKind] = useState('absent')
  const [note, setNote] = useState('')
  const employees = useApi<{ items: { id: number; full_name: string }[] }>(`/employees${qs({ location_id: locationId, status: 'active', size: 200 })}`)
  const list = useApi<{ items: Absence[] }>(`/absences${qs({ location_id: locationId, size: 20 })}`)

  async function record(event: FormEvent) {
    event.preventDefault()
    const ok = await run(() => api('/absences', { body: { employee_id: Number(employeeId), location_id: locationId, day, day_to: dayTo || null, absence_type: kind, note: note || null } }), 'Recorded')
    if (ok) {
      setNote('')
      setOpen(false)
      list.reload()
    }
  }

  async function cancel(event: FormEvent) {
    event.preventDefault()
    if (!cancelling) return
    if (await run(() => api(`/absences/${cancelling.id}/void`, { body: { reason: cancelReason } }), 'Record cancelled')) {
      setCancelling(null)
      setCancelReason('')
      list.reload()
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 p-6 pb-3">
        <CardTitle className="text-lg">Days off, absences and leave</CardTitle>
        {canRecord && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Record</Button>}
      </CardHeader>
      <CardContent className="p-6 pt-2">
        {list.data?.items.length === 0 ? <EmptyState title="Nothing recorded" /> : (
          <ul className="divide-y divide-border">
            {list.data?.items.map((a) => (
              <li key={a.id} className={`flex flex-wrap items-center justify-between gap-3 py-3 text-sm ${a.status === 'void' ? 'opacity-60' : ''}`}>
                <span className="min-w-0">
                  <span className="block font-medium">{a.employee_name}</span>
                  <span className="text-ink-muted">{fmtDate(a.local_date)}{a.status === 'void' ? ` - Cancelled: ${a.void_reason}` : a.note ? ` - ${a.note}` : ''}</span>
                </span>
                <span className="flex items-center gap-2">
                  <Badge tone={a.absence_type === 'absent' ? 'critical' : 'neutral'}>{label(a.absence_type)}</Badge>
                  {canRecord && a.status === 'active' && <Button size="sm" variant="outline" onClick={() => { setCancelling(a); setCancelReason('') }}><Ban className="h-3.5 w-3.5" /> Cancel</Button>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <Modal
        open={open}
        size="lg"
        title="Assign a day off, absence or leave"
        description="Pick one day or a range. It shows on the roster and in attendance."
        onClose={() => setOpen(false)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button type="submit" form="absence-form" disabled={!employeeId}>Record</Button>
        </>}
      >
        <form id="absence-form" onSubmit={record} className="space-y-6">
          <div className="grid gap-5 sm:grid-cols-2">
            {byLocation && <Field label="Location (optional)"><LocationSelect allowAll className="w-full" value={locationId} onChange={(id) => { setLocationId(id); setEmployeeId('') }} /></Field>}
            <Field label="Employee">
              <Select required value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
                <option value="">{employees.data?.items.length === 0 ? 'No employees' : 'Select'}</option>
                {employees.data?.items.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
              </Select>
            </Field>
            <Field label="From"><Input required type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
            <Field label="To (optional)"><Input type="date" value={dayTo} min={day} onChange={(e) => setDayTo(e.target.value)} /></Field>
            <Field label="Type">
              <Select value={kind} onChange={(e) => setKind(e.target.value)}>{ABSENCE_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</Select>
            </Field>
            <Field label="Note"><Input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></Field>
          </div>
        </form>
      </Modal>

      <Modal
        open={cancelling !== null}
        size="md"
        title="Cancel this record"
        description={cancelling ? `${cancelling.employee_name}, ${fmtDate(cancelling.local_date)}, ${label(cancelling.absence_type)}` : undefined}
        onClose={() => setCancelling(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setCancelling(null)}>Keep it</Button>
          <Button type="submit" form="cancel-absence-form" variant="danger">Cancel record</Button>
        </>}
      >
        <form id="cancel-absence-form" onSubmit={cancel} className="space-y-5">
          <Field label="Why is it being cancelled?"><Input required minLength={5} maxLength={500} value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} /></Field>
        </form>
      </Modal>
    </Card>
  )
}

/** A person's own days off, absences and leave, for someone who cannot see everyone's. */
export function MyLeave() {
  const { data } = useApi<Absence[]>('/absences/mine')
  return (
    <Card>
      <CardHeader className="p-6 pb-3"><CardTitle className="text-lg">My days off, absences and leave</CardTitle></CardHeader>
      <CardContent className="p-6 pt-2">
        {!data || data.length === 0 ? <EmptyState title="Nothing recorded for you" /> : (
          <ul className="divide-y divide-border">
            {data.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
                <span>
                  <span className="block font-medium">{fmtDate(a.local_date)}</span>
                  {a.note && <span className="text-ink-muted">{a.note}</span>}
                </span>
                <Badge tone={a.absence_type === 'absent' ? 'critical' : 'neutral'}>{label(a.absence_type)}</Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
