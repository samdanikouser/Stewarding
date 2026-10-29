import { label } from '@/lib/format'

export interface Change {
  field: string
  before: string
  after: string
}

const show = (value: unknown): string =>
  value === null || value === undefined || value === '' ? '-' : typeof value === 'object' ? JSON.stringify(value) : String(value)

/** The fields an audit entry changed, with readable names; fields that stayed the same are left out. */
export function auditChanges(before: Record<string, unknown> | null, after: Record<string, unknown> | null): Change[] {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])]
  return keys
    .filter((key) => show(before?.[key]) !== show(after?.[key]))
    .map((key) => ({ field: label(key.replace(/[._]/g, ' ')), before: show(before?.[key]), after: show(after?.[key]) }))
}

/** One line for a collapsed row: the first change and how many more there are. */
export function auditSummary(changes: Change[], created: boolean): string {
  if (changes.length === 0) return '-'
  if (created) return `${changes.length} ${changes.length === 1 ? 'field' : 'fields'} recorded`
  const [first, ...rest] = changes
  return `${first.field}: ${first.before} to ${first.after}${rest.length ? ` and ${rest.length} more` : ''}`
}
