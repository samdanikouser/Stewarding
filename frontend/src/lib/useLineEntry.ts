import { useState, type KeyboardEvent } from 'react'

export type EntryRow<T> = T & { committed?: boolean }

/** Keyboard entry for repeating line rows: Enter on a complete row commits it and moves to the first field of the next row. */
export function useLineEntry<T extends object>(blank: T, isComplete: (row: T) => boolean, first?: T) {
  const [rows, setRows] = useState<EntryRow<T>[]>([{ ...(first ?? blank) }])
  const [incomplete, setIncomplete] = useState<number | null>(null)
  const [list, setList] = useState<HTMLDivElement | null>(null)

  const update = (index: number, patch: Partial<T>) => {
    setIncomplete(null)
    setRows((all) => all.map((row, n) => (n === index ? { ...row, ...patch, committed: false } : row)))
  }
  const load = (next: T[]) => {
    setIncomplete(null)
    setRows(next.length ? next.map((row) => ({ ...row, committed: true })) : [{ ...blank }])
  }
  /** Changes a row only if it still looks as it did when the change was worked out (an answer that arrives late must not overwrite newer input). */
  const patchIf = (index: number, still: (row: T) => boolean, patch: Partial<T>) =>
    setRows((all) => all.map((row, n) => (n === index && still(row) ? { ...row, ...patch } : row)))
  const addRow = () => setRows((all) => [...all, { ...blank }])
  const remove = (index: number) => setRows((all) => all.filter((_, n) => n !== index))
  const reset = () => {
    setIncomplete(null)
    setRows([{ ...blank }])
  }

  const rowProps = (index: number) => ({
    'data-line-row': index,
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
      if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
      if ((event.target as HTMLElement).closest('button, textarea')) return
      event.preventDefault()
      if (!isComplete(rows[index])) {
        setIncomplete(index)
        return
      }
      setIncomplete(null)
      setRows((all) => {
        const next = all.map((row, n) => (n === index ? { ...row, committed: true } : row))
        return index === next.length - 1 ? [...next, { ...blank }] : next
      })
      requestAnimationFrame(() => list?.querySelector<HTMLElement>(`[data-line-row="${index + 1}"] :is(input, select, textarea)`)?.focus())
    },
  })

  return { rows, update, patchIf, addRow, remove, reset, load, rowProps, attachList: setList, incomplete }
}
