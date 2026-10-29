import { describe, expect, it } from 'vitest'
import { cycleOffset, cycleStart, cycleWeek, weekIndex } from '@/lib/rosterCycle'

describe('rosterCycle', () => {
  it('counts weeks from Monday 6 January 2020, whatever day of the week it is given', () => {
    expect(weekIndex('2020-01-06')).toBe(0)
    expect(weekIndex('2020-01-12')).toBe(0)
    expect(weekIndex('2020-01-13')).toBe(1)
  })

  it('gives the week of the cycle for a start date and an offset, and reads it back', () => {
    const week = cycleWeek('2026-03-04', 2, 1)
    expect(week).toBe((weekIndex('2026-03-04') + 1) % 2)
    expect(cycleOffset('2026-03-04', 2, week)).toBe(1)
  })

  it('names the Monday the pattern first applies', () => {
    expect(cycleStart('2026-03-04', 2, weekIndex('2026-03-04') % 2)).toBe('2026-03-02')
    expect(cycleStart('2026-03-04', 2, (weekIndex('2026-03-04') + 1) % 2)).toBe('2026-03-09')
  })
})
