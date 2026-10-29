import { describe, expect, it } from 'vitest'
import { weekdaysText } from '@/lib/format'

describe('weekdaysText', () => {
  it('writes runs, single days and a whole week', () => {
    expect(weekdaysText([0, 1, 2, 3, 4, 5, 6])).toBe('Every day')
    expect(weekdaysText([0, 1, 2, 3, 4])).toBe('Mon-Fri')
    expect(weekdaysText([0, 1])).toBe('Mon, Tue')
    expect(weekdaysText([0, 2, 3, 4, 6])).toBe('Mon, Wed-Fri, Sun')
    expect(weekdaysText([5])).toBe('Sat')
  })
})
