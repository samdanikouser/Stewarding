import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { api } from '@/lib/api'
import { useRun } from '@/lib/toast'
import { blankField, optionList } from '@/lib/formFields'
import { FieldRestrictions } from '@/pages/FieldEditor'
import type { Schedule } from '@/pages/MonitoringRecordForm'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MEASURES = [['Temperature', '°C'], ['Concentration', 'ppm'], ['pH', ''], ['Time', 'min'], ['Humidity', '%']]

interface CheckFormProps {
  equipmentId: number
  schedule: Schedule | null
  onClose: () => void
  onSaved: () => void
}

export function CheckFormModal({ equipmentId, schedule, onClose, onSaved }: CheckFormProps) {
  const run = useRun()
  const [form, setForm] = useState({
    stage: schedule?.stage ?? '', parameter: schedule?.parameter ?? 'Temperature', unit: schedule?.unit ?? '°C',
    value_type: schedule?.value_type ?? 'number', source: schedule?.source ?? 'machine_display', timing: schedule?.timing ?? 'startup',
    time_of_day: schedule?.time_of_day?.slice(0, 5) ?? '', interval_minutes: schedule?.interval_minutes ? String(schedule.interval_minutes) : '',
    weekdays: schedule?.weekdays ?? [], day_of_month: schedule?.day_of_month ? String(schedule.day_of_month) : '',
    min_value: schedule?.min_value != null ? String(Number(schedule.min_value)) : '', max_value: schedule?.max_value != null ? String(Number(schedule.max_value)) : '',
    require_reference: schedule?.require_reference ?? false, trace_lots: schedule?.trace_lots ?? false, required: schedule?.required ?? true, reference_label: schedule?.reference_label ?? '', phase: schedule?.phase ?? '',
  })
  const [extra, setExtra] = useState({ options: (schedule?.options ?? []).join('\n'), fail: schedule?.fail_options ?? [], maxLength: String(schedule?.max_length ?? 200) })
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }))
  const isNumber = form.value_type === 'number'
  const manual = form.timing === 'manual'
  const toggleDay = (day: number) => set('weekdays', form.weekdays.includes(day) ? form.weekdays.filter((d) => d !== day) : [...form.weekdays, day])

  function pickMeasure(parameter: string) {
    const known = MEASURES.find(([name]) => name === parameter)
    setForm((f) => ({ ...f, parameter, unit: known ? known[1] : f.unit }))
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    const body = {
      stage: form.stage, parameter: form.parameter, unit: isNumber ? form.unit || null : null, value_type: form.value_type,
      require_reference: form.require_reference, trace_lots: form.trace_lots, required: form.required, reference_label: form.require_reference ? form.reference_label.trim() || null : null,
      phase: form.phase || null, source: form.source, timing: form.timing,
      time_of_day: form.time_of_day && !manual ? `${form.time_of_day}:00` : null,
      interval_minutes: form.timing === 'interval' ? Number(form.interval_minutes) : null,
      weekdays: form.weekdays.length && !manual ? form.weekdays : null, day_of_month: form.day_of_month && !manual ? Number(form.day_of_month) : null,
      min_value: isNumber && form.min_value !== '' ? Number(form.min_value) : null,
      max_value: isNumber && form.max_value !== '' ? Number(form.max_value) : null,
      options: form.value_type === 'choice' ? optionList(extra.options) : null,
      fail_options: form.value_type === 'choice' ? extra.fail.filter((o) => optionList(extra.options).includes(o)) : null,
      max_length: form.value_type === 'text' ? Number(extra.maxLength) : null,
    }
    const ok = await run(() => schedule
      ? api(`/equipment/schedules/${schedule.id}`, { method: 'PUT', body })
      : api(`/equipment/${equipmentId}/schedules`, { body }), 'Check saved')
    if (ok) onSaved()
  }

  const toggles: { key: 'required' | 'require_reference' | 'trace_lots'; title: string }[] = [
    { key: 'required', title: 'Mandatory: the form cannot be saved without an answer' },
    { key: 'require_reference', title: 'Ask for a batch, lot or product reference' },
    { key: 'trace_lots', title: 'Link to food lots: the person scans or types the lot, recorded against the delivery' },
  ]

  return (
    <Modal
      open
      size="lg"
      title={schedule ? 'Edit check' : 'Add check'}
      description="Changes are audited and apply to new checks only."
      onClose={onClose}
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="check-form">Save check</Button>
      </>}
    >
      <form id="check-form" onSubmit={save} className="space-y-7">
        <section className="space-y-4">
          <h3 className="text-sm font-semibold">What is checked</h3>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Check name"><Input required value={form.stage} onChange={(e) => set('stage', e.target.value)} /></Field>
            <Field label="Answer type">
              <Select value={form.value_type} onChange={(e) => set('value_type', e.target.value as typeof form.value_type)}>
                <option value="number">A measurement (number)</option>
                <option value="yes_no">Yes or no</option>
                <option value="text">Short text</option>
                <option value="choice">Dropdown (choose one)</option>
                <option value="date">Date picker</option>
                <option value="time">Time picker</option>
                <option value="signature">Signature box</option>
                <option value="image">Image upload</option>
              </Select>
            </Field>
            <Field label="What is checked">
              <Input list="measures" required value={form.parameter} onChange={(e) => pickMeasure(e.target.value)} />
              <datalist id="measures">{MEASURES.map(([name]) => <option key={name} value={name} />)}</datalist>
            </Field>
            <Field label="Reading source">
              <Select value={form.source} onChange={(e) => set('source', e.target.value)}>
                <option value="machine_display">Machine display</option>
                <option value="independent_probe">Independent probe</option>
              </Select>
            </Field>
            {isNumber && <Field label="Unit"><Input maxLength={20} value={form.unit} onChange={(e) => set('unit', e.target.value)} /></Field>}
            {isNumber && <span className="hidden sm:block" />}
            {isNumber && <Field label="Minimum"><Input type="number" step="any" value={form.min_value} onChange={(e) => set('min_value', e.target.value)} /></Field>}
            {isNumber && <Field label="Maximum"><Input type="number" step="any" value={form.max_value} onChange={(e) => set('max_value', e.target.value)} /></Field>}
          </div>
          {(form.value_type === 'text' || form.value_type === 'choice') && (
            <FieldRestrictions value={{ ...blankField(), type: form.value_type, ...extra }} onChange={(v) => setExtra({ options: v.options, fail: v.fail, maxLength: v.maxLength })} />
          )}
        </section>

        <section className="space-y-4 border-t border-border pt-6">
          <h3 className="text-sm font-semibold">When it is checked</h3>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Timing">
              <Select value={form.timing} onChange={(e) => set('timing', e.target.value)}>
                <option value="startup">At startup</option>
                <option value="checkpoint">At a set time</option>
                <option value="interval">Every few minutes</option>
                <option value="manual">On demand (no schedule)</option>
              </Select>
            </Field>
            {!manual && <Field label="First check at"><Input type="time" value={form.time_of_day} onChange={(e) => set('time_of_day', e.target.value)} /></Field>}
            {form.timing === 'interval' && (
              <Field label="Every (minutes)"><Input required type="number" min={1} max={1440} value={form.interval_minutes} onChange={(e) => set('interval_minutes', e.target.value)} /></Field>
            )}
            {!manual && <Field label="Day of month (optional)"><Input type="number" min={1} max={31} value={form.day_of_month} onChange={(e) => set('day_of_month', e.target.value)} /></Field>}
          </div>
          {!manual && (
            <fieldset>
              <legend className="mb-2 text-sm font-medium">Days (none selected means every day)</legend>
              <div className="flex flex-wrap gap-2">
                {DAYS.map((name, day) => (
                  <label key={name} className={`cursor-pointer rounded-full border px-4 py-1.5 text-sm transition-colors ${form.weekdays.includes(day) ? 'border-brand bg-brand-soft font-semibold text-brand-deep' : 'border-border hover:bg-surface-muted'}`}>
                    <input type="checkbox" className="sr-only" checked={form.weekdays.includes(day)} onChange={() => toggleDay(day)} /> {name}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </section>

        <section className="space-y-4 border-t border-border pt-6">
          <h3 className="text-sm font-semibold">How it is recorded</h3>
          <Field label="Entry type">
            <Select value={form.phase} onChange={(e) => set('phase', e.target.value as typeof form.phase)}>
              <option value="">Single entry</option>
              <option value="start">Time in (starts an entry)</option>
              <option value="finish">Time out (closes an entry)</option>
            </Select>
          </Field>
          <div className="divide-y divide-border rounded-xl border border-border">
            {toggles.map((t) => (
              <label key={t.key} className="flex cursor-pointer items-start gap-3 px-4 py-3 text-sm">
                <input type="checkbox" className="mt-0.5" checked={form[t.key]} onChange={(e) => set(t.key, e.target.checked)} /> {t.title}
              </label>
            ))}
          </div>
          {form.require_reference && <Field label="What is the reference called?"><Input maxLength={40} value={form.reference_label} onChange={(e) => set('reference_label', e.target.value)} /></Field>}
        </section>
      </form>
    </Modal>
  )
}
