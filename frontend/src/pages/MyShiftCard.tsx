import { LogIn, LogOut } from 'lucide-react'
import { useRef, useState } from 'react'
import { LocationSelect } from '@/components/LocationSelect'
import { FaceCapture, type FaceEvidence, type FaceResult } from '@/components/FaceCapture'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Skeleton } from '@/components/ui/table'
import { api, ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { Step } from '@/lib/face'
import { fmtTime } from '@/lib/format'
import { currentPosition } from '@/lib/geo'
import { useRun, useToast } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

interface ShiftStatus {
  checked_in: boolean
  server_time: string
  employee: string
  employee_code: string
  record: { check_in_at: string; late_minutes: number } | null
  location?: { id: number; name: string; timezone: string; geofence: boolean }
  shift?: string
  incomplete_task_count: number
  face_required: boolean
  face_enrolled: boolean
  rostered_today: { location_id: number; location_name: string; shift: string; start: string; end: string; week_off: boolean }[]
}

interface Challenge {
  token: string
  steps: Step[]
}

export function MyShiftCard({ onChange }: { onChange?: () => void }) {
  const run = useRun()
  const toast = useToast()
  const { data, loading, reload } = useApi<ShiftStatus>('/attendance/me/status')
  const [picked, setPicked] = useState<number | null>(null)
  const [elsewhere, setElsewhere] = useState(false)
  const rostered = data?.rostered_today ?? []
  const working = rostered.filter((r) => !r.week_off)
  const locationId = picked ?? working[0]?.location_id ?? null
  const locked = new Set(working.map((r) => r.location_id)).size === 1 && !elsewhere
  const { me } = useAuth()
  const byLocation = me?.by_location !== false
  // without a chosen location the server finds the one the position fits, so send the position when any of mine has a boundary
  const fencedFor = (id: number | null) => (byLocation ? me?.locations.find((l) => l.id === id)?.geofence : me?.locations.some((l) => l.geofence))
  const placeFor = (id: number | null) => (byLocation ? { location_id: id } : {})
  const [exceptionOpen, setExceptionOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [faceFor, setFaceFor] = useState<'in' | 'out' | null>(null)
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const proof = useRef<Record<string, unknown> | null>(null)

  const refresh = () => {
    reload()
    onChange?.()
  }

  async function newChallenge(direction: 'in' | 'out') {
    const made = await api<{ required: boolean; token?: string; steps?: Step[] }>('/attendance/face-challenge', { body: { action: direction } })
    setChallenge(made.required && made.token && made.steps ? { token: made.token, steps: made.steps } : null)
  }

  async function needFace(direction: 'in' | 'out') {
    if (!data?.face_enrolled) {
      toast('error', 'Your face is not enrolled yet. Ask your manager to enroll it')
      return
    }
    try {
      await newChallenge(direction)
      setFaceFor(direction)
    } catch (err) {
      toast('error', err instanceof Error ? err.message : 'Could not start the camera check')
    }
  }

  async function verifyFace(template: number[], evidence: FaceEvidence): Promise<FaceResult> {
    const faceBody = { face: template, ...(challenge ? { challenge: challenge.token, liveness: evidence.liveness, snapshot: evidence.snapshot } : {}) }
    try {
      if (faceFor === 'in') {
        const fenced = fencedFor(locationId)
        await api('/attendance/check-in', { body: { ...placeFor(locationId), ...faceBody, ...(fenced ? await currentPosition() : {}) } })
        toast('ok', 'Checked in')
      } else {
        const where = data?.location?.geofence ? await currentPosition() : {}
        await api('/attendance/check-out', { body: { ...faceBody, ...where } })
        toast('ok', 'Checked out')
      }
      setTimeout(() => { setFaceFor(null); refresh() }, 1200)
      return { ok: true, message: 'Match found!' }
    } catch (err) {
      if (faceFor === 'out' && err instanceof ApiError && err.status === 409 && typeof err.detail === 'object') {
        proof.current = faceBody
        setFaceFor(null)
        setExceptionOpen(true)
        return { ok: true, message: 'Match found!' }
      }
      if (faceFor) await newChallenge(faceFor).catch(() => undefined)
      return { ok: false, message: err instanceof Error ? err.message : 'Could not verify your face' }
    }
  }

  async function checkIn() {
    if (byLocation && locationId === null) return
    if (data?.face_required) return needFace('in')
    const fenced = fencedFor(locationId)
    const ok = await run(async () => api('/attendance/check-in', { body: { ...placeFor(locationId), ...(fenced ? await currentPosition() : {}) } }), 'Checked in')
    if (ok) refresh()
  }

  async function checkOut(withReason?: string) {
    try {
      const where = data?.location?.geofence ? await currentPosition() : {}
      await api('/attendance/check-out', { body: { exception_reason: withReason ?? null, ...(proof.current ?? {}), ...where } })
      toast('ok', 'Checked out')
      proof.current = null
      setExceptionOpen(false)
      setReason('')
      refresh()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && typeof err.detail === 'object') setExceptionOpen(true)
      else toast('error', err instanceof Error ? err.message : 'Check-out failed')
    }
  }

  if (loading && !data) return <Skeleton className="h-40 w-full" />
  if (!data) return null

  return (
    <Card className="overflow-hidden">
      <div className={cn('flex flex-wrap items-center justify-between gap-3 px-6 py-5', data.checked_in ? 'bg-brand-soft' : 'bg-surface-muted/70')}>
        <div className="min-w-0">
          <p className="truncate text-lg font-semibold">{data.employee}</p>
          <p className="text-sm text-ink-muted">{data.employee_code}</p>
        </div>
        <Badge tone={data.checked_in ? 'ok' : 'neutral'} className="px-3 py-1 text-sm">{data.checked_in ? 'On duty' : 'Not checked in'}</Badge>
      </div>
      <CardContent className="space-y-6 p-6">
        {data.checked_in && data.record && data.location ? (
          <>
            <p className="text-base">Checked in at <span className="font-semibold">{fmtTime(data.record.check_in_at, data.location.timezone)}</span>{byLocation && <> at {data.location.name}</>}.</p>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div><dt className="text-ink-muted">Shift</dt><dd className="text-base font-medium">{data.shift ?? 'Unscheduled'}</dd></div>
              <div><dt className="text-ink-muted">Open tasks</dt><dd className="text-base font-medium">{data.incomplete_task_count}</dd></div>
            </dl>
            {data.record.late_minutes > 0 && <Badge tone="warn">Checked in {data.record.late_minutes} min late</Badge>}
            <Button className="h-14 w-full text-base" onClick={() => (data.face_required ? needFace('out') : checkOut())}>
              <LogOut className="h-5 w-5" /> Check out
            </Button>
          </>
        ) : (
          <>
            <div className="space-y-1 rounded-xl bg-surface-muted/70 px-4 py-3 text-sm">
              <p className="font-medium">Today</p>
              {rostered.length === 0 ? <p className="text-ink-muted">You are not on the roster today.</p> : rostered.map((r) => (
                <p key={`${r.location_id}-${r.shift}`} className="text-ink-muted">
                  {r.week_off ? <>Week off{byLocation && <> at {r.location_name}</>}</> : <>{r.shift}, {r.start} to {r.end}{byLocation && <>, at <span className="font-medium text-ink">{r.location_name}</span></>}</>}
                </p>
              ))}
            </div>
            {!byLocation ? null : locked ? (
              <div className="space-y-1">
                <p className="text-sm font-medium">Where are you working?</p>
                <p className="flex min-h-12 items-center rounded-lg border border-border bg-surface-muted px-3 text-base font-medium">{working[0].location_name} (rostered today)</p>
                <button type="button" className="min-h-11 text-sm font-medium text-brand-deep hover:underline" onClick={() => setElsewhere(true)}>Working somewhere else?</button>
              </div>
            ) : (
              <Field label="Where are you working?"><LocationSelect className="h-12 w-full text-base" value={locationId} preferred={working.map((r) => r.location_id)} onChange={setPicked} /></Field>
            )}
            <Button className="h-14 w-full text-base" disabled={byLocation && locationId === null} onClick={checkIn}>
              <LogIn className="h-5 w-5" /> Check in
            </Button>
          </>
        )}
      </CardContent>

      <Modal
        open={faceFor !== null}
        size="md"
        title={faceFor === 'in' ? 'Check in with your face' : 'Check out with your face'}
        description="Look at the camera and follow the steps."
        onClose={() => setFaceFor(null)}
      >
        {faceFor !== null && <FaceCapture steps={challenge?.steps} onCapture={verifyFace} />}
      </Modal>

      <Modal
        open={exceptionOpen}
        size="md"
        title="Tasks still open"
        description={`${data.incomplete_task_count} mandatory task(s) not finished. Say why you are leaving.`}
        onClose={() => setExceptionOpen(false)}
        footer={<>
          <Button variant="outline" onClick={() => setExceptionOpen(false)}>Go back</Button>
          <Button variant="danger" disabled={reason.trim().length < 5} onClick={() => checkOut(reason)}>Check out with reason</Button>
        </>}
      >
        <Field label="Reason">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </Modal>
    </Card>
  )
}
