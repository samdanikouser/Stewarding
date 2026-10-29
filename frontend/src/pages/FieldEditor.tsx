import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { FIELD_TYPES, optionList, type FieldSpec, type FieldType } from '@/lib/formFields'

interface RestrictionsProps {
  value: FieldSpec
  onChange: (next: FieldSpec) => void
}

/** The rules that go with the chosen answer type: limits, length, or the list of answers. */
export function FieldRestrictions({ value, onChange }: RestrictionsProps) {
  const set = (patch: Partial<FieldSpec>) => onChange({ ...value, ...patch })
  const options = optionList(value.options)
  const toggleFail = (option: string) => set({ fail: value.fail.includes(option) ? value.fail.filter((o) => o !== option) : [...value.fail, option] })
  return (
    <div className="space-y-3">
      {value.type === 'number' && (
        <div className="grid grid-cols-3 gap-3">
          <Field label="Unit"><Input maxLength={20} value={value.unit} onChange={(e) => set({ unit: e.target.value })} /></Field>
          <Field label="Minimum"><Input type="number" step="any" value={value.min} onChange={(e) => set({ min: e.target.value })} /></Field>
          <Field label="Maximum"><Input type="number" step="any" value={value.max} onChange={(e) => set({ max: e.target.value })} /></Field>
        </div>
      )}
      {value.type === 'text' && (
        <Field label="Longest answer (characters)"><Input type="number" min={1} max={500} className="w-32" value={value.maxLength} onChange={(e) => set({ maxLength: e.target.value })} /></Field>
      )}
      {value.type === 'choice' && (
        <>
          <Field label="Answers to choose from">
            <textarea rows={4} value={value.options} onChange={(e) => set({ options: e.target.value, fail: value.fail.filter((o) => optionList(e.target.value).includes(o)) })}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-brand" />
          </Field>
          {options.length > 0 && (
            <fieldset>
              <legend className="mb-1 text-sm font-medium">Which answers count as a failure? (optional)</legend>
              <div className="flex flex-wrap gap-3">
                {options.map((o) => <label key={o} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={value.fail.includes(o)} onChange={() => toggleFail(o)} /> {o}</label>)}
              </div>
            </fieldset>
          )}
        </>
      )}
    </div>
  )
}

interface FieldEditorProps extends RestrictionsProps {
  index: number
  count: number
  onMove: (delta: number) => void
  onRemove: () => void
}

export function FieldEditor({ value, onChange, index, count, onMove, onRemove }: FieldEditorProps) {
  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-48 flex-1">
          <Field label={`Field ${index + 1} title`}>
            <Input required maxLength={60} placeholder="For example Core temperature" value={value.title} onChange={(e) => onChange({ ...value, title: e.target.value })} />
          </Field>
        </div>
        <Field label="Answer type">
          <Select value={value.type} onChange={(e) => onChange({ ...value, type: e.target.value as FieldType })}>
            {FIELD_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </Select>
        </Field>
        <div className="flex gap-1">
          <Button type="button" variant="ghost" size="icon" aria-label="Move up" disabled={index === 0} onClick={() => onMove(-1)}><ArrowUp className="h-4 w-4" /></Button>
          <Button type="button" variant="ghost" size="icon" aria-label="Move down" disabled={index === count - 1} onClick={() => onMove(1)}><ArrowDown className="h-4 w-4" /></Button>
          <Button type="button" variant="ghost" size="icon" aria-label="Remove field" disabled={count === 1} onClick={onRemove}><Trash2 className="h-4 w-4" /></Button>
        </div>
      </div>
      <FieldRestrictions value={value} onChange={onChange} />
      <div role="radiogroup" aria-label="Is this question mandatory" className="inline-flex rounded-lg border border-border p-0.5 text-sm">
        {([true, false] as const).map((req) => (
          <button key={String(req)} type="button" role="radio" aria-checked={value.required === req} onClick={() => onChange({ ...value, required: req })}
            className={value.required === req ? 'rounded-md bg-brand px-3 py-1 font-medium text-brand-ink' : 'rounded-md px-3 py-1 text-ink-muted hover:text-ink'}>
            {req ? 'Mandatory' : 'Optional'}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={value.reference} onChange={(e) => onChange({ ...value, reference: e.target.checked })} /> Also ask for a batch or lot reference with this field</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={value.traceLots} onChange={(e) => onChange({ ...value, traceLots: e.target.checked })} /> Link this field to food lots (traceability): scan or type the lot</label>
    </div>
  )
}
