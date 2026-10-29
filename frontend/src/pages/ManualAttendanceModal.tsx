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

export function ManualAttendanceModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const run = useRun()
  const { me } = useAuth()
  const byLocation = me?.by_location !== false  // when attendance is not by location, no outlet is asked for
  const [locationId, setLocationId] = useState<number | null>(null)
  const [employeeId, setEmployeeId] = useState('')
  const [day, setDay] = useState(() => iso(new Date(Date.now() - 86400000)))
  const [checkIn, setCheckIn] = useState('06:00')
  const [checkOut, setCheckOut] = useState('14:00')
  const [reason, setReason] = useState('')
  const employees = useApi<{ items: { id: number; full_name: string }[] }>(`/employees${qs({ location_id: locationId, status: 'active', size: 200 })}`)

  async function save(event: FormEvent) {
    event.preventDefault()
    const body = { employee_id: Number(employeeId), location_id: locationId, day, check_in_time: `${checkIn}:00`, check_out_time: `${checkOut}:00`, reason }
    if (await run(() => api('/attendance/manual', { body }), 'Attendance added')) onSaved()
  }

  return (
    <Modal
      open
      size="lg"
      title="Add missing attendance"
      description="For someone who worked but did not check in or out. The person and the reason are recorded."
      onClose={onClose}
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="manual-attendance-form" disabled={!employeeId}>Add attendance</Button>
      </>}
    >
      <form id="manual-attendance-form" onSubmit={save} className="space-y-6">
        <div className="grid gap-5 sm:grid-cols-2">
          {byLocation && <Field label="Location (optional)"><LocationSelect allowAll className="w-full" value={locationId} onChange={(id) => { setLocationId(id); setEmployeeId('') }} /></Field>}
          <Field label="Employee">
            <Select required value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
              <option value="">{employees.data?.items.length === 0 ? 'No employees' : 'Select'}</option>
              {employees.data?.items.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
            </Select>
          </Field>
        </div>
        <div className="grid gap-5 sm:grid-cols-3">
          <Field label="Date"><Input required type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
          <Field label="Punch in"><Input required type="time" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} /></Field>
          <Field label={`Punch out${checkIn && checkOut && checkOut < checkIn ? ' (next day)' : ''}`}><Input required type="time" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} /></Field>
        </div>
        <Field label="Reason"><Input required minLength={5} maxLength={500} placeholder="For example: forgot to punch, confirmed by the supervisor" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </form>
    </Modal>
  )
}
