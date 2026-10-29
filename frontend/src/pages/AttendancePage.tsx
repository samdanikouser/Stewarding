import { Clock, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { LocationSelect } from '@/components/LocationSelect'
import { SectionTabs } from '@/components/SectionTabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { EmptyState, Skeleton, SkeletonRows, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDate, fmtDateTime, fmtTime, hoursMinutes } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { AbsencePanel, MyLeave } from '@/pages/AbsencePanel'
import { FaceSnapshotButton } from '@/pages/FaceSnapshotButton'
import { DayOffModal } from '@/pages/DayOffModal'
import { ManualAttendanceModal } from '@/pages/ManualAttendanceModal'

interface Record {
  id: number
  employee_name?: string
  location_id: number
  local_date: string
  check_in_at: string
  check_out_at: string | null
  late_minutes: number
  payable_minutes: number | null
  overtime_minutes: number | null
  exception_reason: string | null
  open: boolean
  missed_checkout: boolean
  geo_flags: string[]
  snapshot_in?: boolean
  snapshot_out?: boolean
}

interface Listing {
  total: number
  items: Record[]
}

const SIZE = 15

export function AttendancePage() {
  const { me } = useAuth()
  const run = useRun()
  const canView = me?.permissions.includes('attendance.view') ?? false
  const canCorrect = me?.permissions.includes('attendance.correct') ?? false
  const canMarkOff = me?.permissions.includes('attendance.absence') ?? false
  const [locationId, setLocationId] = useState<number | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const [correcting, setCorrecting] = useState<Record | null>(null)
  const [removing, setRemoving] = useState<Record | null>(null)
  const [field, setField] = useState('check_out_at')
  const [value, setValue] = useState('')
  const [reason, setReason] = useState('')
  const [adding, setAdding] = useState(false)
  const [markingOff, setMarkingOff] = useState(false)
  const [tab, setTab] = useState<'records' | 'leave'>('records')

  const path = canView
    ? `/attendance${qs({ location_id: locationId, date_from: from, date_to: to, page, size: SIZE })}`
    : `/attendance/mine${qs({ page, size: SIZE })}`
  const { data, loading, reload } = useApi<Listing>(path)
  const byLocation = me?.by_location !== false
  const locationNames = new Map(me?.locations.map((l) => [l.id, l.name]))

  function startCorrection(r: Record) {
    setCorrecting(r)
    setField(r.check_out_at ? 'check_out_at' : 'check_in_at')
    setValue('')
    setReason('')
  }

  async function submitCorrection(event: FormEvent) {
    event.preventDefault()
    if (!correcting) return
    const ok = field === 'day_off'
      ? await run(() => api(`/attendance/${correcting.id}/day-off`, { body: { reason } }), 'Changed to a day off')
      : await run(() => api(`/attendance/${correcting.id}/correct`, { body: { field, new_value: new Date(value).toISOString(), reason } }), 'Attendance corrected')
    if (ok) {
      setCorrecting(null)
      reload()
    }
  }

  async function submitRemoval(event: FormEvent) {
    event.preventDefault()
    if (!removing) return
    const ok = await run(() => api(`/attendance/${removing.id}/remove`, { body: { reason } }), 'Attendance record deleted')
    if (ok) {
      setRemoving(null)
      reload()
    }
  }

  const flags = (r: Record) => (
    <>
      {r.late_minutes > 0 && <Badge tone="warn">Late {r.late_minutes}m</Badge>}
      {r.missed_checkout && <Badge tone="critical">Missed checkout</Badge>}
      {canView && r.snapshot_in && <FaceSnapshotButton recordId={r.id} which="in" who={r.employee_name} />}
      {canView && r.snapshot_out && <FaceSnapshotButton recordId={r.id} which="out" who={r.employee_name} />}
      {r.geo_flags?.length > 0 && <Badge tone="warn" title={[...new Set(r.geo_flags)].join('; ')}>Location unverified</Badge>}
      {r.exception_reason?.startsWith('Manual entry') ? <Badge title={r.exception_reason}>Manual entry</Badge>
        : r.exception_reason && <Badge tone="warn" title={r.exception_reason}>Exception</Badge>}
    </>
  )

  const actions = (r: Record) => (
    <>
      <Button size="sm" variant="outline" onClick={() => startCorrection(r)}><Pencil className="h-3.5 w-3.5" /> Correct</Button>
      <Button size="sm" variant="outline" className="border-danger/40 text-danger hover:bg-danger-soft" onClick={() => { setRemoving(r); setReason('') }}><Trash2 className="h-3.5 w-3.5" /> Delete</Button>
    </>
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold">Attendance</h1>
        <Link to="/check-in" className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-brand-deep hover:underline">Check in or out</Link>
      </div>
      <SectionTabs label="Attendance" active={tab} onSelect={(key) => setTab(key as 'records' | 'leave')}
        groups={[{ title: canView ? 'Everyone\'s records' : 'My records', items: [{ key: 'records', label: 'Records' }] }, { title: 'Leave and absences', items: [{ key: 'leave', label: 'Leave' }] }]} />

      {tab === 'leave' && (canView ? <AbsencePanel canRecord={me?.permissions.includes('attendance.absence') ?? false} /> : <MyLeave />)}

      {tab === 'records' && <section className="space-y-4" aria-label="Attendance records">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{canView ? 'Attendance records' : 'My attendance history'}</h2>
          {canMarkOff && <Button variant="outline" onClick={() => setMarkingOff(true)}><Plus className="h-4 w-4" /> Mark day off</Button>}
          {canCorrect && <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> Add missing attendance</Button>}
        </div>
        {canView && (
          <div className="filter-bar">
            {byLocation && <LocationSelect allowAll value={locationId} onChange={(id) => { setLocationId(id); setPage(1) }} />}
            <Input aria-label="From date" type="date" className="w-auto" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1) }} />
            <Input aria-label="To date" type="date" className="w-auto" value={to} onChange={(e) => { setTo(e.target.value); setPage(1) }} />
          </div>
        )}

        <ul className="space-y-3 xl:hidden">
          {loading && !data ? <li><Skeleton className="h-28 w-full" /></li> : data?.items.map((r) => (
            <li key={r.id} className="space-y-3 rounded-xl border border-border bg-surface p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-semibold">{canView ? r.employee_name : fmtDate(r.local_date)}</p>
                  <p className="text-sm text-ink-muted">{canView ? fmtDate(r.local_date) : ''}{canView && byLocation ? ', ' : ''}{byLocation && locationNames.get(r.location_id)}</p>
                </div>
                <span className="flex shrink-0 items-center gap-1.5 text-sm font-medium"><Clock aria-hidden className="h-4 w-4 text-ink-muted" />{fmtTime(r.check_in_at)} - {r.open ? 'On duty' : fmtTime(r.check_out_at)}</span>
              </div>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-xs text-ink-muted">Worked</dt><dd>{hoursMinutes(r.payable_minutes)}</dd></div>
                <div><dt className="text-xs text-ink-muted">Overtime</dt><dd>{hoursMinutes(r.overtime_minutes)}</dd></div>
              </dl>
              <div className="flex flex-wrap gap-1.5">{flags(r)}</div>
              {canCorrect && <div className="flex flex-wrap gap-2 border-t border-border pt-3">{actions(r)}</div>}
            </li>
          ))}
        </ul>

        <div className="hidden xl:block">
          <Table>
            <thead>
              <tr>
                <Th>Date</Th>
                {canView && <Th>Employee</Th>}
                {byLocation && <Th>Location</Th>}
                <Th>In</Th>
                <Th>Out</Th>
                <Th>Worked</Th>
                <Th>Overtime</Th>
                <Th>Flags</Th>
                {canCorrect && <Th />}
              </tr>
            </thead>
            <tbody>
              {loading && !data ? <SkeletonRows cols={byLocation ? 8 : 7} /> : data?.items.map((r) => (
                <tr key={r.id}>
                  <Td>{fmtDate(r.local_date)}</Td>
                  {canView && <Td className="font-medium">{r.employee_name}</Td>}
                  {byLocation && <Td>{locationNames.get(r.location_id)}</Td>}
                  <Td>{fmtTime(r.check_in_at)}</Td>
                  <Td>{r.open ? 'On duty' : fmtTime(r.check_out_at)}</Td>
                  <Td>{hoursMinutes(r.payable_minutes)}</Td>
                  <Td>{hoursMinutes(r.overtime_minutes)}</Td>
                  <Td><span className="flex flex-wrap gap-1.5">{flags(r)}</span></Td>
                  {canCorrect && <Td><div className="flex gap-2">{actions(r)}</div></Td>}
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
        {data?.items.length === 0 && <EmptyState title="No attendance records" />}
        {data && <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />}
      </section>}

      {markingOff && <DayOffModal onClose={() => setMarkingOff(false)} onSaved={() => { setMarkingOff(false); reload() }} />}
      {adding && <ManualAttendanceModal onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload() }} />}

      <Modal
        open={correcting !== null}
        title="Correct attendance"
        description={correcting ? `${correcting.employee_name ?? 'Your record'}, ${fmtDate(correcting.local_date)}` : undefined}
        size="md"
        onClose={() => setCorrecting(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setCorrecting(null)}>Cancel</Button>
          <Button type="submit" form="correct-form">Apply correction</Button>
        </>}
      >
        {correcting && (
          <form id="correct-form" onSubmit={submitCorrection} className="space-y-5">
            <dl className="grid grid-cols-2 gap-4 rounded-xl bg-surface-muted p-4 text-sm">
              <div><dt className="text-xs text-ink-muted">Checked in</dt><dd className="font-medium">{fmtDateTime(correcting.check_in_at)}</dd></div>
              <div><dt className="text-xs text-ink-muted">Checked out</dt><dd className="font-medium">{correcting.check_out_at ? fmtDateTime(correcting.check_out_at) : 'Still on duty'}</dd></div>
            </dl>
            <Field label="What to correct">
              <Select value={field} onChange={(e) => setField(e.target.value)}>
                <option value="check_in_at">Check-in time</option>
                <option value="check_out_at">Check-out time</option>
                {canMarkOff && <option value="day_off">Change this to a day off</option>}
              </Select>
            </Field>
            {field === 'day_off'
              ? <p className="text-sm text-ink-muted">The check-in and check-out are removed and the day is recorded as a day off. They stay in the audit log with your reason.</p>
              : <Field label="New time (your local time)"><Input required type="datetime-local" value={value} onChange={(e) => setValue(e.target.value)} /></Field>}
            <Field label="Reason"><Input required minLength={5} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          </form>
        )}
      </Modal>

      <Modal
        open={removing !== null}
        title="Delete attendance record"
        description={removing ? `${removing.employee_name ?? 'Your record'}, ${fmtDate(removing.local_date)}, ${fmtTime(removing.check_in_at)} to ${removing.open ? 'now' : fmtTime(removing.check_out_at)}` : undefined}
        size="md"
        onClose={() => setRemoving(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setRemoving(null)}>Cancel</Button>
          <Button type="submit" form="remove-form" variant="danger">Delete record</Button>
        </>}
      >
        <form id="remove-form" onSubmit={submitRemoval} className="space-y-5">
          <p className="text-sm text-ink-muted">Use this for a record entered by mistake. Its details and your reason stay in the audit log. To change a time instead, use Correct.</p>
          <Field label="Reason"><Input required minLength={5} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        </form>
      </Modal>
    </div>
  )
}
