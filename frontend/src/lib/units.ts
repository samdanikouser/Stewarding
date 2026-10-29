export interface Balance {
  qty: number
  unit: string
  portioned: number
  waste: number
  left: number
  unmeasured: number
}

export interface Cut {
  size: string
  unit: string
  count: string
  waste: string
}

// What a unit measures and its size in the smallest unit; any other unit only compares with itself.
const UNITS: Record<string, [string, number]> = { kg: ['mass', 1000], g: ['mass', 1], l: ['volume', 1000], ml: ['volume', 1] }

const measure = (unit: string): [string, number] => {
  const name = unit.trim().toLowerCase()
  return UNITS[name] ?? [name, 1]
}

const round = (value: number) => Math.round(value * 100) / 100

/** The total of one cut, its size times the number of portions; empty until both are typed. */
export function cutTotal(cut: Pick<Cut, 'size' | 'count'>): number | null {
  const size = Number(cut.size)
  const count = Number(cut.count)
  return cut.size === '' || cut.count === '' || !(size > 0) || !(count > 0) ? null : round(size * count)
}

/** An amount in the unit that reads best: 4800 g as 4.8 kg, 1500 ml as 1.5 l. */
export function amountText(amount: number, unit: string): string {
  const name = unit.trim().toLowerCase()
  if (name === 'g' && amount >= 1000) return `${round(amount / 1000)} kg`
  if (name === 'ml' && amount >= 1000) return `${round(amount / 1000)} l`
  return `${round(amount)} ${unit}`
}

/** What the cuts typed so far use and lose, in the lot's own unit; cuts in an unrelated unit or without a size are left out. */
export function cutsUse(balance: Balance, cuts: Cut[]): { portions: number; waste: number } {
  const [kind, size] = measure(balance.unit)
  let portions = 0
  let waste = 0
  for (const cut of cuts) {
    const [cutKind, cutSize] = measure(cut.unit)
    if (cutKind !== kind || !cut.unit.trim()) continue
    portions += (cutTotal(cut) ?? 0) * cutSize
    waste += (cut.waste === '' ? 0 : Number(cut.waste)) * cutSize
  }
  return { portions: round(portions / size), waste: round(waste / size) }
}
