import { AlertTriangle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ScanButton } from '@/components/ScanButton'
import { WorkLocationSelect } from '@/components/WorkLocationSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Modal } from '@/components/ui/modal'
import { EmptyState } from '@/components/ui/table'
import { useAuth } from '@/lib/auth'
import { fmtTime, label } from '@/lib/format'
import { cycleOf } from '@/lib/monitoring'
import { qs, useApi } from '@/lib/useApi'
import { CorrectiveActionsPanel } from '@/pages/CorrectiveActionsPanel'
import { MonitoringLog } from '@/pages/MonitoringLog'
import { MonitoringRecordForm, type EquipmentItem, type Prefill } from '@/pages/MonitoringRecordForm'

interface Due {
  equipment_id: number
  equipment: string
  schedule_id: number
  stage: string
  slot_at: string
  opens_at: string
  open: boolean
  status: 'done' | 'due' | 'overdue' | 'upcoming'
}

interface Pending {
  start_reading_id: number
  equipment_id: number
  equipment: string
  item: string | null
  started_at: string
  minutes_open: number
}

const RANK = { overdue: 3, due: 2, upcoming: 1, done: 0 } as const
const TONE = { done: 'ok', due: 'warn', overdue: 'critical', upcoming: 'neutral' } as const

export function MonitoringPage() {
  const { me } = useAuth()
  const arrived = useLocation().state as { locationId?: number; equipmentId?: number } | null
  const [locationId, setLocationId] = useState<number | null>(arrived?.locationId ?? null)
  const opened = useRef(false)
  const [prefill, setPrefill] = useState<Prefill | null>(null)
  const [recording, setRecording] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const canRecord = me?.permissions.includes('temp.record') ?? false
  const timezone = me?.locations.find((l) => l.id === locationId)?.timezone

  const equipment = useApi<EquipmentItem[]>(locationId ? `/monitoring/equipment${qs({ location_id: locationId, k: refreshKey })}` : null)
  const due = useApi<Due[]>(locationId ? `/monitoring/due${qs({ location_id: locationId, k: refreshKey })}` : null)
  const pending = useApi<Pending[]>(locationId ? `/monitoring/pending${qs({ location_id: locationId, k: refreshKey })}` : null)
  const items = equipment.data ?? []
  const overdue = (due.data ?? []).filter((d) => d.status === 'overdue')
  const refresh = () => setRefreshKey((k) => k + 1)
  const startRecording = (next: Prefill | null) => {
    setPrefill(next)
    setRecording(true)
  }
  const stopRecording = () => {
    setPrefill(null)
    setRecording(false)
  }

  // a check is recorded when its latest slot that has started is done
  const doneSchedules = (() => {
    const latest = new Map<number, Due>()
    for (const d of due.data ?? []) {
      if (d.status === 'upcoming') continue
      const seen = latest.get(d.schedule_id)
      if (!seen || d.slot_at > seen.slot_at) latest.set(d.schedule_id, d)
    }
    return new Set([...latest.values()].filter((d) => d.status === 'done').map((d) => d.schedule_id))
  })()

  // a scheduled check stays closed until its grace period before the due time begins
  const closedSchedules = (() => {
    const bySchedule = new Map<number, Due[]>()
    for (const d of due.data ?? []) bySchedule.set(d.schedule_id, [...(bySchedule.get(d.schedule_id) ?? []), d])
    return new Set([...bySchedule].filter(([, list]) => list.every((d) => d.status === 'upcoming' && !d.open)).map(([id]) => id))
  })()

  // checks of one point due at the same time are shown, and recorded, as one card
  const cards = (() => {
    const out = new Map<string, { first: Due; stages: string[]; status: Due['status']; closed: boolean }>()
    for (const d of due.data ?? []) {
      const sched = items.find((e) => e.id === d.equipment_id)?.schedules.find((s) => s.id === d.schedule_id)
      const group = sched ? cycleOf(sched, items.find((e) => e.id === d.equipment_id)!.schedules).map((s) => s.id).sort().join() : String(d.schedule_id)
      const key = `${d.equipment_id}|${d.slot_at}|${group}`
      const card = out.get(key)
      if (!card) out.set(key, { first: d, stages: [d.stage], status: d.status, closed: closedSchedules.has(d.schedule_id) })
      else {
        card.stages.push(d.stage)
        if (RANK[d.status] > RANK[card.status]) card.status = d.status
      }
    }
    return [...out.entries()]
  })()
  const todo = cards.filter(([, card]) => card.status !== 'done')
  const finished = cards.filter(([, card]) => card.status === 'done')

  // arriving from a scanned code opens the first check that is due at that point
  useEffect(() => {
    if (opened.current || !arrived?.equipmentId || !due.data) return
    opened.current = true
    const next = todo.find(([, card]) => card.first.equipment_id === arrived.equipmentId && !card.closed)
    if (next) startRecording({ equipmentId: arrived.equipmentId, scheduleId: next[1].first.schedule_id })
  })

  function timeOut(p: Pending) {
    const finish = items.find((e) => e.id === p.equipment_id)?.schedules.find((s) => s.active && s.phase === 'finish')
    if (finish) startRecording({ equipmentId: p.equipment_id, scheduleId: finish.id, startReadingId: p.start_reading_id, item: p.item })
  }

  function retest(equipmentId: number, readingId: number, stage: string) {
    const schedule = items.find((e) => e.id === equipmentId)?.schedules.find((s) => s.stage === stage)
    if (schedule) startRecording({ equipmentId, scheduleId: schedule.id, retestOf: readingId })
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Monitoring</h1>
        <div className="flex flex-wrap items-center gap-3">
          {me?.permissions.includes('equipment.manage') && <Link to="/settings/monitoring" className="text-sm font-medium text-brand-deep underline-offset-4 hover:underline">Manage monitoring points</Link>}
          {canRecord && <ScanButton />}
          {canRecord && <Button onClick={() => startRecording(null)}>Record a check</Button>}
          <WorkLocationSelect value={locationId} onChange={setLocationId} />
        </div>
      </div>

      {overdue.length > 0 && (
        <div role="alert" className="flex items-center gap-2 rounded-xl border border-danger/20 border-l-4 border-l-danger bg-danger-soft px-4 py-3 text-sm font-medium text-danger">
          <AlertTriangle className="h-4 w-4" aria-hidden /> {overdue.length} check(s) overdue
        </div>
      )}

      <Card>
        <CardHeader><CardTitle>Checks due today</CardTitle></CardHeader>
        <CardContent>
          {cards.length === 0 ? <EmptyState title="No scheduled checks here" /> : todo.length === 0 ? (
            <EmptyState title="All of today's checks are recorded" />
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {todo.map(([key, { first: d, stages, status, closed }]) => (
                <li key={key}>
                  <button type="button" disabled={!canRecord || closed}
                    onClick={() => startRecording({ equipmentId: d.equipment_id, scheduleId: d.schedule_id })}
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-left text-sm enabled:hover:bg-surface-muted">
                    <span><span className="block font-medium">{d.equipment}</span><span className="text-ink-muted">{stages.map(label).join(' and ')} at {fmtTime(d.slot_at, timezone)}</span></span>
                    <Badge tone={TONE[status]}>{closed ? `Opens ${fmtTime(d.opens_at, timezone)}` : label(status)}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {finished.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-sm font-medium text-ink-muted">Recorded today ({finished.length})</summary>
              <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {finished.map(([key, { first: d, stages }]) => (
                  <li key={key} className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm">
                    <span><span className="block font-medium">{d.equipment}</span><span className="text-ink-muted">{stages.map(label).join(' and ')} at {fmtTime(d.slot_at, timezone)}</span></span>
                    <Badge tone="ok">Done</Badge>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </CardContent>
      </Card>

      {(pending.data ?? []).length > 0 && (
        <Card>
          <CardHeader><CardTitle>Waiting for time out</CardTitle></CardHeader>
          <CardContent>
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {pending.data!.map((p) => (
                <li key={p.start_reading_id}>
                  <button type="button" disabled={!canRecord} onClick={() => timeOut(p)}
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-left text-sm enabled:hover:bg-surface-muted">
                    <span><span className="block font-medium">{p.item ?? p.equipment}</span><span className="text-ink-muted">{p.equipment}, in at {fmtTime(p.started_at, timezone)}, {Math.floor(p.minutes_open / 60)} h {p.minutes_open % 60} min ago</span></span>
                    <Badge tone="warn">Pending</Badge>
                  </button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Modal open={canRecord && recording} size="lg" title={prefill?.retestOf ? 'Record a retest' : prefill?.startReadingId ? 'Record the time out' : 'Record a check'} description="Pick the monitoring point; the checks that are open now appear together." onClose={stopRecording}>
        <MonitoringRecordForm equipment={items} prefill={prefill} doneSchedules={doneSchedules} closedSchedules={closedSchedules} onSaved={() => { refresh(); stopRecording() }} onClearRetest={stopRecording} />
      </Modal>

      <CorrectiveActionsPanel locationId={locationId} equipment={items} refreshKey={refreshKey} onRetest={retest} onChanged={refresh} />

      <h2 className="pt-2 text-lg font-semibold">Monitoring log</h2>
      <MonitoringLog locationId={locationId} equipment={items} refreshKey={refreshKey} />
    </div>
  )
}
