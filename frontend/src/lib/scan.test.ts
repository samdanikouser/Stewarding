import { describe, expect, it } from 'vitest'
import { scanCode } from '@/lib/scan'

describe('scanCode', () => {
  it('takes the code from a link and passes a bare code through', () => {
    expect(scanCode('https://plato.example.com/scan/e12.abc123?x=1')).toBe('e12.abc123')
    expect(scanCode('  l3.def456  ')).toBe('l3.def456')
  })
})
