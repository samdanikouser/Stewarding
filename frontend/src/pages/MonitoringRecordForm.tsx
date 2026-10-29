import { useEffect, useState, type FormEvent } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { LotPicker, type LotChoice } from '@/components/LotPicker'
import { SignaturePad } from '@/components/SignaturePad'
import { Select } from '@/components/ui/select'
import { api, uploadFile } from '@/lib/api'
import { label } from '@/lib/format'
import { cycleOf } from '@/lib/monitoring'
import { useRun } from '@/lib/toast'
import { useLookup } from '@/lib/useLookups'

export interface Schedule {
  id: number
  stage: string
  parameter: string
  unit: string | null
  value_type: 'number' | 'yes_no' | 'text' | 'choice' | 'date' | 'time' | 'signature' | 'image'
  options: string[] | null
  fail_options: string[] | null
  max_length: number | null
  require_reference: boolean
  trace_lots?: boolean
  required: boolean
  reference_label: string | null
  phase: 'start' | 'finish' | null
  source: string
  timing: string
  min_value: number | string | null
  max_value: number | string | null
  time_of_day: string | null
  interval_minutes: number | null
  weekdays: number[]
  day_of_month: number | null
  active: boolean
}

export interface EquipmentItem {
  id: number
  code: string
  name: string
  kind: string
  location_id: number
  status: string
  active: boolean
  supervisor_id: number | null
  procedure_reference: string | null
  maintenance_notes: string | null
  schedules: Schedule[]
  needs_attention: boolean
  recent_failures: number
}

export interface Prefill {
  equipmentId: number
  scheduleId: number
  retestOf?: number
  startReadingId?: number
  item?: string | null
}

interface RecordFormProps {
  equipment: EquipmentItem[]
  prefill: Prefill | null
  onSaved: () => void
  onClearRetest: () => void
  doneSchedules?: Set<number>
  closedSchedules?: Set<number>
}

const num = (v: number | string | null) => (v === null ? null : Number(v))

/** The answer in the form the server expects: a number for measurements and yes or no, words for text and choices. */
function answerOf(s: Schedule | undefined, raw: string | undefined) {
  return s && ['text', 'choice', 'date', 'time'].includes(s.value_type) ? { answer: raw ?? '' } : { value: Number(raw) }
}

function verdict(value: string, schedule?: Schedule): 'pass' | 'fail' | null {
  if (value === '' || !schedule) return null
  if (schedule.value_type === 'yes_no') return value === '1' ? 'pass' : 'fail'
  if (['text', 'date', 'time', 'signature', 'image'].includes(schedule.value_type)) return 'pass'
  if (schedule.value_type === 'choice') return schedule.fail_options?.includes(value) ? 'fail' : 'pass'
  const amount = Number(value)
  const low = num(schedule.min_value)
  const high = num(schedule.max_value)
  return (low === null || amount >= low) && (high === null || amount <= high) ? 'pass' : 'fail'
}

/** One schedule per group of checks that are due together. */
function firstOfEachCycle(schedules: Schedule[]): Schedule[] {
  return schedules.filter((s) => s.phase !== 'finish' && cycleOf(s, schedules)[0] === s)
}

const limitsText = (s: { min_value?: string | number | null; max_value?: string | number | null }) =>
  s.min_value != null && s.max_value != null ? ` ${s.min_value}-${s.max_value}` : s.max_value != null ? ` max ${s.max_value}` : s.min_value != null ? ` min ${s.min_value}` : ''

export function MonitoringRecordForm({ equipment, prefill, onSaved, onClearRetest, doneSchedules, closedSchedules }: RecordFormProps) {
  const run = useRun()
  const standardActions = useLookup('corrective_action')
  const [equipmentId, setEquipmentId] = useState('')
  const [scheduleId, setScheduleId] = useState('')
  const [values, setValues] = useState<Record<number, string>>({})
  const [reference, setReference] = useState('')
  const [lots, setLots] = useState<LotChoice[]>([])
  const [comment, setComment] = useState('')
  const [action, setAction] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [blobs, setBlobs] = useState<Record<number, Blob>>({})

  useEffect(() => {
    if (!prefill) return
    setEquipmentId(String(prefill.equipmentId))
    setScheduleId(String(prefill.scheduleId))
    setValues({})
  }, [prefill])

  const selected = equipment.find((e) => String(e.id) === equipmentId)
  const schedules = selected?.schedules.filter((s) => s.active) ?? []
  const schedule = schedules.find((s) => String(s.id) === scheduleId)
  const fullCycle = schedule ? (prefill?.retestOf ? [schedule] : cycleOf(schedule, schedules)) : []
  const outstanding = prefill?.retestOf || prefill?.startReadingId ? fullCycle : fullCycle.filter((s) => !doneSchedules?.has(s.id))
  const cycle = outstanding.length > 0 ? outstanding : fullCycle
  const cycles = availableCycles(schedules)
  const results = cycle.map((s) => verdict(values[s.id] ?? '', s))
  const anyFail = results.includes('fail')
  const complete = cycle.length > 0 && cycle.every((s) => !s.required || (values[s.id] ?? '') !== '')
  const title = (s: Schedule) => `${fullCycle.length > 1 && label(s.stage) !== s.parameter ? `${label(s.stage)}: ${s.parameter}` : s.parameter}${s.required ? '' : ' (optional)'}`
  const setBlob = (s: Schedule, blob: Blob | null) => {
    setBlobs((b) => ({ ...b, ...(blob ? { [s.id]: blob } : {}) }))
    setValues((v) => ({ ...v, [s.id]: blob ? 'file' : '' }))
  }
  const needsReference = cycle.some((s) => s.require_reference && !s.trace_lots)
  const needsLots = !prefill?.startReadingId && !prefill?.retestOf && cycle.some((s) => s.trace_lots)
  const alreadyDone = !prefill?.retestOf && cycle.length > 0 && cycle.every((s) => doneSchedules?.has(s.id))

  function availableCycles(list: Schedule[]): Schedule[] {
    return firstOfEachCycle(list).filter((c) => {
      const group = cycleOf(c, list)
      return !group.every((s) => closedSchedules?.has(s.id)) && !group.every((s) => doneSchedules?.has(s.id))
    })
  }

  function pickPoint(id: string) {
    const list = equipment.find((e) => String(e.id) === id)?.schedules.filter((s) => s.active) ?? []
    const only = availableCycles(list)
    setEquipmentId(id)
    setScheduleId(only.length === 1 ? String(only[0].id) : '')
    setValues({})
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    const ok = await run(async () => {
      const evidence = file ? await uploadFile(file) : null
      const common = { comment: comment || null, evidence_path: evidence, corrective_action: action || null, reference: reference || null, lot_ids: lots.map((l) => l.id) }
      const body = { equipment_id: Number(equipmentId), start_reading_id: prefill?.startReadingId ?? null }
      if (prefill?.retestOf) {
        await api('/monitoring/readings', { body: { equipment_id: Number(equipmentId), schedule_id: Number(scheduleId), ...answerOf(schedule, values[Number(scheduleId)]), retest_of_id: prefill.retestOf, ...common } })
      } else {
        const readings = []
        for (const s of cycle.filter((c) => (values[c.id] ?? '') !== '')) {
          const answer = s.value_type === 'signature' || s.value_type === 'image' ? { answer: await uploadFile(blobs[s.id] instanceof File ? (blobs[s.id] as File) : new File([blobs[s.id]], 'signature.png', { type: 'image/png' })) } : answerOf(s, values[s.id])
          readings.push({ schedule_id: s.id, ...answer, ...common })
        }
        await api('/monitoring/readings/batch', { body: { ...body, readings } })
      }
    }, anyFail ? 'Failed check recorded - supervisor notified' : cycle.length > 1 ? 'Checks recorded' : 'Check recorded')
    setBusy(false)
    if (ok) {
      setValues({})
      setReference('')
      setLots([])
      setComment('')
      setAction('')
      setFile(null)
      setEquipmentId('')
      setScheduleId('')
      onClearRetest()
      onSaved()
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {prefill?.retestOf && (
        <p className="flex items-center justify-between rounded-md bg-warn-soft px-3 py-2 text-sm text-warn">
          Retest of reading #{prefill.retestOf}
          <button type="button" className="underline" onClick={onClearRetest}>Cancel retest</button>
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Monitoring point">
          <Select required value={equipmentId} disabled={!!prefill?.retestOf}
            onChange={(e) => pickPoint(e.target.value)}>
            <option value="">Select monitoring point</option>
            {equipment.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </Select>
        </Field>
        {cycles.length > 1 && (
          <Field label="Check">
            <Select required value={scheduleId} disabled={!!prefill?.retestOf} onChange={(e) => { setScheduleId(e.target.value); setValues({}) }}>
              <option value="">Select check</option>
              {cycles.map((s) => (
                <option key={s.id} value={s.id} disabled={cycleOf(s, schedules).every((c) => doneSchedules?.has(c.id))}>{cycleOf(s, schedules).map((c) => label(c.stage)).join(' and ')}{s.time_of_day ? ` at ${s.time_of_day.slice(0, 5)}` : ''}{cycleOf(s, schedules).every((c) => doneSchedules?.has(c.id)) ? ' (recorded)' : ''}</option>
              ))}
            </Select>
          </Field>
        )}
      </div>
      {selected && !prefill?.retestOf && cycles.length === 0 && <p className="rounded-md bg-surface-muted px-3 py-2 text-sm">Nothing is open for this point right now. Checks open shortly before they are due.</p>}
      {prefill?.startReadingId && <p className="rounded-md bg-surface-muted px-3 py-2 text-sm">Time out for <span className="font-medium">{prefill.item ?? 'this entry'}</span>. The time out is stamped when you save.</p>}
      {alreadyDone && <p role="alert" className="rounded-md bg-ok-soft px-3 py-2 text-sm text-ok">This check is already recorded for this time. It is due again at the next scheduled time.</p>}
      <div className="space-y-3">
        {cycle.map((s, i) => (
          <div key={s.id} className="flex flex-wrap items-end gap-3">
            {s.value_type === 'yes_no' ? (
              <Field label={title(s)}>
                <Select required={s.required} className="w-36" value={values[s.id] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [s.id]: e.target.value }))}>
                  <option value="">Select</option>
                  <option value="1">Yes</option>
                  <option value="0">No</option>
                </Select>
              </Field>
            ) : s.value_type === 'choice' ? (
              <Field label={title(s)}>
                <Select required={s.required} className="w-52" value={values[s.id] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [s.id]: e.target.value }))}>
                  <option value="">Select</option>
                  {s.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                </Select>
              </Field>
            ) : s.value_type === 'signature' ? (
              <Field label={title(s)}><SignaturePad onChange={(png) => setBlob(s, png)} /></Field>
            ) : s.value_type === 'image' ? (
              <Field label={title(s)}>
                <Input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(e) => setBlob(s, e.target.files?.[0] ?? null)} />
              </Field>
            ) : s.value_type === 'date' || s.value_type === 'time' ? (
              <Field label={title(s)}>
                <Input required={s.required} type={s.value_type} className="w-44" value={values[s.id] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [s.id]: e.target.value }))} />
              </Field>
            ) : s.value_type === 'text' ? (
              <Field label={title(s)}>
                <Input required={s.required} maxLength={s.max_length ?? 200} className="w-72" value={values[s.id] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [s.id]: e.target.value }))} />
              </Field>
            ) : (
              <Field label={`${fullCycle.length > 1 ? `${label(s.stage)}: ` : ''}${s.parameter}${s.unit ? ` (${s.unit})` : ''}${limitsText(s)}`}>
                <Input required={s.required} type="number" step="any" inputMode="decimal" className="w-36" value={values[s.id] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [s.id]: e.target.value }))} />
              </Field>
            )}
            {results[i] && !['text', 'date', 'time', 'signature', 'image'].includes(s.value_type) && <Badge tone={results[i] === 'pass' ? 'ok' : 'critical'}>{results[i] === 'pass' ? (s.value_type === 'number' ? 'Within limits' : 'OK') : s.value_type === 'number' ? 'Out of range' : 'Fails'}</Badge>}
          </div>
        ))}
        {needsReference && (
          <div className="space-y-1.5">
            <p className="text-sm font-medium">{cycle.find((s) => s.reference_label)?.reference_label ?? 'Batch, lot or product'}</p>
            <LotPicker value={lots} onChange={setLots} allowCustom={{ value: reference, onChange: setReference }} />
          </div>
        )}
        {needsLots && (
          <Field label="Food lot or lots">
            <LotPicker value={lots} onChange={setLots} />
          </Field>
        )}
      </div>
      {anyFail && (
        <div className="space-y-2 rounded-xl border border-danger/20 border-l-4 border-l-danger bg-danger-soft p-3">
          <p className="text-sm font-medium text-danger">A failed check will be recorded as failed and your supervisor alerted.</p>
          <Field label="Corrective action taken">
            <Input list="standard-actions" value={action} onChange={(e) => setAction(e.target.value)} />
            <datalist id="standard-actions">{standardActions.map((a) => <option key={a} value={a} />)}</datalist>
          </Field>
        </div>
      )}
      <Field label="Comments (optional)"><Input value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
      <Field label="Photo evidence (optional)">
        <Input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      <div className="sticky -bottom-5 -mx-6 -mb-5 border-t border-border bg-surface px-6 py-4">
        <Button type="submit" className="w-full sm:w-auto" disabled={busy || alreadyDone || !complete || (needsReference && reference.trim() === '' && lots.length === 0) || (needsLots && lots.length === 0)}>
          {busy ? 'Saving...' : prefill?.retestOf ? 'Record retest' : cycle.length > 1 ? 'Record all' : 'Record check'}
        </Button>
      </div>
    </form>
  )
}
