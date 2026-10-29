import { afterEach, describe, expect, it } from 'vitest'
import { fmtMoney, setCurrency } from '@/lib/money'

describe('fmtMoney', () => {
  afterEach(() => setCurrency(''))

  it('shows the bare amount until a currency is set, then leads with it', () => {
    expect(fmtMoney(2.5)).toBe('2.500')
    setCurrency(' KWD ')
    expect(fmtMoney(2.5)).toBe('KWD 2.500')
  })
})
