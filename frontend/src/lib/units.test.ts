import { describe, expect, it } from 'vitest'
import { amountText, cutTotal, cutsUse, type Balance } from '@/lib/units'

const lot = (unit: string): Balance => ({ qty: 20, unit, portioned: 0, waste: 0, left: 20, unmeasured: 0 })
const cut = (size: string, unit: string, count: string, waste = '') => ({ size, unit, count, waste })

describe('cutTotal', () => {
  it('multiplies the size by the number of portions', () => {
    expect(cutTotal(cut('200', 'g', '24'))).toBe(4800)
    expect(cutTotal(cut('0.25', 'kg', '10'))).toBe(2.5)
  })

  it('is empty until both are typed and positive', () => {
    expect(cutTotal(cut('', 'g', '24'))).toBeNull()
    expect(cutTotal(cut('200', 'g', ''))).toBeNull()
    expect(cutTotal(cut('0', 'g', '5'))).toBeNull()
    expect(cutTotal(cut('200', 'g', '-1'))).toBeNull()
  })
})

describe('amountText', () => {
  it('shows large grams and millilitres in the bigger unit', () => {
    expect(amountText(4800, 'g')).toBe('4.8 kg')
    expect(amountText(1500, 'ml')).toBe('1.5 l')
    expect(amountText(750, 'g')).toBe('750 g')
    expect(amountText(3, 'kg')).toBe('3 kg')
  })
})

describe('cutsUse', () => {
  it('turns every cut into the lot unit and adds portions and waste separately', () => {
    expect(cutsUse(lot('kg'), [cut('200', 'g', '24', '600'), cut('1', 'kg', '2', '0.1')])).toEqual({ portions: 6.8, waste: 0.7 })
  })

  it('ignores letter case and spaces in the unit', () => {
    expect(cutsUse(lot('kg'), [cut('500', ' G ', '2'), cut('1', 'KG', '1')])).toEqual({ portions: 2, waste: 0 })
  })

  it('converts litres and millilitres but never mixes mass with volume', () => {
    expect(cutsUse(lot('l'), [cut('250', 'ml', '4'), cut('2', 'kg', '1', '1')])).toEqual({ portions: 1, waste: 0 })
  })

  it('compares an unknown unit only with the same word', () => {
    expect(cutsUse(lot('pcs'), [cut('1', 'PCS', '3'), cut('1', 'kg', '3')])).toEqual({ portions: 3, waste: 0 })
  })

  it('leaves out cuts with no size or no unit', () => {
    expect(cutsUse(lot('kg'), [cut('', 'kg', '4'), cut('4', '', '1')])).toEqual({ portions: 0, waste: 0 })
  })
})
