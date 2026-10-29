export type FieldType = 'number' | 'yes_no' | 'text' | 'choice' | 'date' | 'time' | 'signature' | 'image'

export interface FieldSpec {
  title: string
  type: FieldType
  unit: string
  min: string
  max: string
  options: string
  fail: string[]
  maxLength: string
  reference: boolean
  traceLots: boolean
  required: boolean
}

export const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: 'number', label: 'Number' },
  { value: 'yes_no', label: 'Yes or no' },
  { value: 'text', label: 'Short text' },
  { value: 'date', label: 'Date picker' },
  { value: 'time', label: 'Time picker' },
  { value: 'signature', label: 'Signature box' },
  { value: 'image', label: 'Image upload' },
  { value: 'choice', label: 'Dropdown (choose one)' },
]

export const blankField = (): FieldSpec => ({ title: '', type: 'number', unit: '', min: '', max: '', options: '', fail: [], maxLength: '200', reference: false, traceLots: false, required: true })

export const optionList = (text: string): string[] => [...new Set(text.split('\n').map((o) => o.trim().replace(/\s+/g, ' ')).filter(Boolean))]

/** What is wrong with a field, in words, or null when it can be saved. */
export function fieldProblem(f: FieldSpec): string | null {
  if (f.title.trim().length < 2) return 'Give every field a title.'
  if (f.type === 'number') {
    if (f.min === '' && f.max === '') return `${f.title}: a number needs a minimum or a maximum. For anything without limits use Short text.`
    if (f.min !== '' && f.max !== '' && Number(f.min) > Number(f.max)) return `${f.title}: the minimum is above the maximum.`
  }
  if (f.type === 'choice') {
    const options = optionList(f.options)
    if (options.length < 2) return `${f.title}: list at least two answers, one per line.`
    if (options.length > 20) return `${f.title}: at most 20 answers.`
  }
  if (f.type === 'text' && (Number(f.maxLength) < 1 || Number(f.maxLength) > 500)) return `${f.title}: the maximum length is between 1 and 500.`
  return null
}

export function fieldPayload(f: FieldSpec) {
  const options = optionList(f.options)
  return {
    title: f.title.trim(), value_type: f.type, require_reference: f.reference, trace_lots: f.traceLots, required: f.required,
    unit: f.type === 'number' ? f.unit.trim() || null : null,
    min_value: f.type === 'number' && f.min !== '' ? Number(f.min) : null,
    max_value: f.type === 'number' && f.max !== '' ? Number(f.max) : null,
    options: f.type === 'choice' ? options : null,
    fail_options: f.type === 'choice' ? f.fail.filter((o) => options.includes(o)) : null,
    max_length: f.type === 'text' ? Number(f.maxLength) : null,
  }
}
