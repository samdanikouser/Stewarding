import { describe, expect, it } from 'vitest'
import { auditChanges, auditSummary } from '@/lib/auditDiff'

describe('auditChanges', () => {
  it('lists only the fields that changed, with readable names', () => {
    const changes = auditChanges({ 'reminder.lead_minutes': 30, name: 'Main', same: 1 }, { 'reminder.lead_minutes': 45, name: 'Main', same: 1 })
    expect(changes).toEqual([{ field: 'Reminder lead minutes', before: '30', after: '45' }])
  })

  it('shows every field of a new record and marks empty values', () => {
    expect(auditChanges(null, { code: 'MK', note: null })).toEqual([
      { field: 'Code', before: '-', after: 'MK' },
    ])
    expect(auditChanges({ active: true }, null)).toEqual([{ field: 'Active', before: 'true', after: '-' }])
  })

  it('writes nested values as text', () => {
    expect(auditChanges({ days: [1, 2] }, { days: [1, 2, 3] })[0]).toEqual({ field: 'Days', before: '[1,2]', after: '[1,2,3]' })
  })
})

describe('auditSummary', () => {
  it('is a dash when nothing changed', () => {
    expect(auditSummary([], false)).toBe('-')
  })

  it('counts the fields of a new record', () => {
    expect(auditSummary(auditChanges(null, { a: 1, b: 2 }), true)).toBe('2 fields recorded')
    expect(auditSummary(auditChanges(null, { a: 1 }), true)).toBe('1 field recorded')
  })

  it('shows the first change and how many more follow', () => {
    expect(auditSummary(auditChanges({ a: 1, b: 2, c: 3 }, { a: 2, b: 3, c: 4 }), false)).toBe('A: 1 to 2 and 2 more')
    expect(auditSummary(auditChanges({ a: 1 }, { a: 2 }), false)).toBe('A: 1 to 2')
  })
})
