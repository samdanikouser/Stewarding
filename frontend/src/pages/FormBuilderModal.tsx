import { Plus, X } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { blankField, fieldPayload, fieldProblem, FIELD_TYPES, optionList, type FieldSpec } from '@/lib/formFields'
import { useRun } from '@/lib/toast'
import { useLookup } from '@/lib/useLookups'
import { FieldEditor } from '@/pages/FieldEditor'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MODES = [
  ['daily', 'Every day'],
  ['weekly', 'On certain days of the week'],
  ['monthly', 'Once a month'],
  ['interval', 'Every few minutes'],
  ['on_demand', 'No schedule - fill in whenever needed'],
] as const
const STEPS = ['About the form', 'Fields', 'How often']

interface FormBuilderProps {
  initialLocation: number | null
  onClose: () => void
  onCreated: () => void
}

export function FormBuilderModal({ initialLocation, onClose, onCreated }: FormBuilderProps) {
  const { me } = useAuth()
  const run = useRun()
  const types = useLookup('monitoring_type')
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [kind, setKind] = useState('Other')
  const [locations, setLocations] = useState<number[]>(initialLocation ? [initialLocation] : [])
  const [fields, setFields] = useState<FieldSpec[]>([blankField()])
  const [mode, setMode] = useState<(typeof MODES)[number][0]>('daily')
  const [times, setTimes] = useState<string[]>(['08:00'])
  const [weekdays, setWeekdays] = useState<number[]>([])
  const [dayOfMonth, setDayOfMonth] = useState('1')
  const [interval, setInterval] = useState('120')
  const [start, setStart] = useState('06:00')
  const [problem, setProblem] = useState<string | null>(null)

  const setField = (i: number, next: FieldSpec) => setFields((all) => all.map((f, n) => (n === i ? next : f)))
  const moveField = (i: number, delta: number) => setFields((all) => {
    const copy = [...all]
    ;[copy[i], copy[i + delta]] = [copy[i + delta], copy[i]]
    return copy
  })
  const toggle = <T,>(list: T[], value: T) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

  function check(forStep: number): string | null {
    if (forStep === 0) {
      if (name.trim().length < 2) return 'Give the form a name, for example Cooking log.'
      if (locations.length === 0) return 'Choose at least one location.'
    }
    if (forStep === 1) {
      const titles = fields.map((f) => f.title.trim().toLowerCase())
      if (new Set(titles).size !== titles.length) return 'Two fields have the same title.'
      return fields.map(fieldProblem).find(Boolean) ?? null
    }
    if (forStep === 2) {
      if (mode === 'interval' && (!Number(interval) || Number(interval) < 5)) return 'Checks can be at most every 5 minutes apart.'
      if (mode !== 'interval' && mode !== 'on_demand' && (times.length === 0 || times.some((t) => !t) || new Set(times).size !== times.length)) return 'Give at least one time, each different.'
      if (mode === 'weekly' && weekdays.length === 0) return 'Choose the days of the week.'
      if (mode === 'monthly' && !(Number(dayOfMonth) >= 1 && Number(dayOfMonth) <= 31)) return 'Choose a day of the month from 1 to 31.'
    }
    return null
  }

  function next() {
    const found = check(step)
    setProblem(found)
    if (!found) setStep(step + 1)
  }

  async function create() {
    const found = check(0) ?? check(1) ?? check(2)
    setProblem(found)
    if (found) return
    const frequency = mode === 'on_demand' ? { mode, times: [] }
      : mode === 'interval' ? { mode, interval_minutes: Number(interval), start: `${start}:00` }
      : { mode, times: times.map((t) => `${t}:00`), weekdays: mode === 'weekly' ? weekdays : null, day_of_month: mode === 'monthly' ? Number(dayOfMonth) : null }
    const body = { name, kind, location_ids: locations, fields: fields.map(fieldPayload), frequency }
    if (await run(() => api('/equipment/forms', { body }), locations.length > 1 ? 'Form created at each location' : 'Form created')) onCreated()
  }

  return (
    <Modal
      open
      size="xl"
      title="Create a log form"
      description="A form people fill in for a monitoring point, in three short steps."
      onClose={onClose}
      footer={<>
        <Button type="button" variant="outline" onClick={step === 0 ? onClose : () => { setProblem(null); setStep(step - 1) }}>{step === 0 ? 'Cancel' : 'Back'}</Button>
        {step < 2 ? <Button type="button" onClick={next}>Next</Button> : <Button type="button" onClick={create}>Create form</Button>}
      </>}
    >
      <ol className="mb-7 flex items-center gap-2 text-sm" aria-label="Steps">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === step ? 'step' : undefined} className="flex flex-1 items-center gap-2">
            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${i <= step ? 'bg-brand text-brand-ink' : 'border border-border text-ink-muted'}`}>{i + 1}</span>
            <span className={i === step ? 'font-semibold' : 'text-ink-muted'}>{label}</span>
            {i < STEPS.length - 1 && <span aria-hidden className="h-px flex-1 bg-border" />}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <div className="space-y-5">
          <Field label="Form name">
            <Input autoFocus maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Kind of log">
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              {[...new Set([...types, 'Other'])].map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
          </Field>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Where is it used?</legend>
            <div className="flex flex-wrap gap-2">
              {me?.locations.map((l) => (
                <label key={l.id} className={`cursor-pointer rounded-full border px-4 py-1.5 text-sm transition-colors ${locations.includes(l.id) ? 'border-brand bg-brand-soft font-semibold text-brand-deep' : 'border-border hover:bg-surface-muted'}`}><input type="checkbox" className="sr-only" checked={locations.includes(l.id)} onChange={() => setLocations((all) => toggle(all, l.id))} /> {l.name}</label>
              ))}
            </div>
          </fieldset>
        </div>
      )}

      {step === 1 && (
        <div className="space-y-3">
          {fields.map((f, i) => (
            <FieldEditor key={i} index={i} count={fields.length} value={f} onChange={(next) => setField(i, next)}
              onMove={(delta) => moveField(i, delta)} onRemove={() => setFields((all) => all.filter((_, n) => n !== i))} />
          ))}
          <Button type="button" variant="outline" onClick={() => setFields((all) => [...all, blankField()])}><Plus className="h-4 w-4" /> Add field</Button>
          <div className="rounded-lg border border-dashed border-border p-4">
            <p className="mb-2 text-sm font-medium">Preview: {name.trim() || 'Your form'}</p>
            <ul className="grid gap-2 sm:grid-cols-2">
              {fields.map((f, i) => (
                <li key={i} className="rounded-md bg-surface-muted px-3 py-2 text-sm">
                  <span className="font-medium">{f.title || `Field ${i + 1}`}{f.type === 'number' && f.unit ? ` (${f.unit})` : ''}</span>
                  <span className="block text-xs text-ink-muted">
                    {FIELD_TYPES.find((t) => t.value === f.type)?.label}
                    {f.type === 'number' && (f.min || f.max) ? `, ${f.min || 'any'} to ${f.max || 'any'}` : ''}
                    {f.type === 'choice' ? `: ${optionList(f.options).join(', ') || 'no answers yet'}` : ''}
                    {f.type === 'text' ? `, up to ${f.maxLength || 200} characters` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <Field label="How often is it filled in?">
            <Select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
              {MODES.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
            </Select>
          </Field>
          {mode === 'weekly' && (
            <fieldset>
              <legend className="mb-1 text-sm font-medium">Which days?</legend>
              <div className="flex flex-wrap gap-2">{DAYS.map((d, i) => <label key={d} className={`cursor-pointer rounded-full border px-4 py-1.5 text-sm transition-colors ${weekdays.includes(i) ? 'border-brand bg-brand-soft font-semibold text-brand-deep' : 'border-border hover:bg-surface-muted'}`}><input type="checkbox" className="sr-only" checked={weekdays.includes(i)} onChange={() => setWeekdays((all) => toggle(all, i))} /> {d}</label>)}</div>
            </fieldset>
          )}
          {mode === 'monthly' && <Field label="Day of the month"><Input type="number" min={1} max={31} className="w-28" value={dayOfMonth} onChange={(e) => setDayOfMonth(e.target.value)} /></Field>}
          {mode === 'on_demand' ? (
            <p className="rounded-md bg-surface-muted px-3 py-2 text-sm">No reminders and nothing becomes overdue. Staff open Monitoring, choose this form under Record a check, and fill it in whenever they need it.</p>
          ) : mode === 'interval' ? (
            <div className="flex flex-wrap gap-3">
              <Field label="Every (minutes)"><Input type="number" min={5} max={1440} className="w-32" value={interval} onChange={(e) => setInterval(e.target.value)} /></Field>
              <Field label="First one at"><Input type="time" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
            </div>
          ) : (
            <fieldset>
              <legend className="mb-1 text-sm font-medium">At what time(s)?</legend>
              <div className="space-y-2">
                {times.map((t, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input type="time" aria-label={`Time ${i + 1}`} className="w-36" value={t} onChange={(e) => setTimes((all) => all.map((x, n) => (n === i ? e.target.value : x)))} />
                    {times.length > 1 && <Button type="button" variant="ghost" size="icon" aria-label="Remove time" onClick={() => setTimes((all) => all.filter((_, n) => n !== i))}><X className="h-4 w-4" /></Button>}
                  </div>
                ))}
                {times.length < 6 && <Button type="button" variant="outline" size="sm" onClick={() => setTimes((all) => [...all, ''])}><Plus className="h-4 w-4" /> Add another time</Button>}
              </div>
            </fieldset>
          )}
        </div>
      )}

      {problem && <p role="alert" className="mt-5 rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">{problem}</p>}
    </Modal>
  )
}
