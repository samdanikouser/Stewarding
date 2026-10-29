import { useState, type FormEvent } from 'react'
import { LocationSelect } from '@/components/LocationSelect'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { api } from '@/lib/api'
import { iso } from '@/lib/dates'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { useAuth } from '@/lib/auth'

/** Marks one employee off for one day, from the attendance list, without going to the leave tab or the shift schedule. */
export function DayOffModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const run = useRun()
  const { me } = useAuth()
  const byLocation = me?.by_location !== false  // when attendance is not by location, no outlet is asked for
  const [locationId, setLocationId] = useState<number | null>(null)
  const [employeeId, setEmployeeId] = useState('')
  const [day, setDay] = useState(() => iso(new Date()))
  const [note, setNote] = useState('')
  const employees = useApi<{ items: { id: number; full_name: string }[] }>(`/employees${qs({ location_id: locationId, status: 'active', size: 200 })}`)

  async function save(event: FormEvent) {
    event.preventDefault()
    const body = { employee_id: Number(employeeId), location_id: locationId, day, absence_type: 'day_off', note: note || null }
    if (await run(() => api('/absences', { body }), 'Day off recorded')) onSaved()
  }

  return (
    <Modal
      open
      size="lg"
      title="Mark a day off"
      description="Records the day as a day off for one person. It shows on the roster and in attendance."
      onClose={onClose}
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="day-off-form" disabled={!employeeId}>Mark day off</Button>
      </>}
    >
      <form id="day-off-form" onSubmit={save} className="grid gap-5 sm:grid-cols-2">
        {byLocation && <Field label="Location (optional)"><LocationSelect allowAll className="w-full" value={locationId} onChange={(id) => { setLocationId(id); setEmployeeId('') }} /></Field>}
        <Field label="Employee">
          <Select required value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">{employees.data?.items.length === 0 ? 'No employees' : 'Select'}</option>
            {employees.data?.items.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </Select>
        </Field>
        <Field label="Date"><Input required type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        <Field label="Note (optional)"><Input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </form>
    </Modal>
  )
}
