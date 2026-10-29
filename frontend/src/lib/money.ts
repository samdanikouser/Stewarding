import { useSyncExternalStore } from 'react'

let code = ''
const listeners = new Set<() => void>()

/** Sets the currency shown with amounts; an empty code shows the bare number. */
export function setCurrency(next: string | null | undefined) {
  const value = (next ?? '').trim()
  if (value === code) return
  code = value
  listeners.forEach((l) => l())
}

/** An amount to three decimals, led by the organization's currency when one is set. */
export const fmtMoney = (n: number) => (code ? `${code} ${n.toFixed(3)}` : n.toFixed(3))

/** The same formatter, and the component draws again when the currency is changed. */
export function useMoney() {
  useSyncExternalStore((cb) => (listeners.add(cb), () => void listeners.delete(cb)), () => code)
  return fmtMoney
}
