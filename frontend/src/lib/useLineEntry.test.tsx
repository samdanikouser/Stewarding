import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useLineEntry } from '@/lib/useLineEntry'

const blank = { item: '', qty: '' }
const complete = (row: typeof blank) => row.item !== '' && Number(row.qty) > 0

describe('useLineEntry', () => {
  it('starts with one blank row', () => {
    const { result } = renderHook(() => useLineEntry(blank, complete))
    expect(result.current.rows).toEqual([blank])
  })

  it('starts from a suggested first row, as the transfer shortcut passes in', () => {
    const { result } = renderHook(() => useLineEntry(blank, complete, { item: '7', qty: '40' }))
    expect(result.current.rows).toEqual([{ item: '7', qty: '40' }])
  })

  it('goes back to a blank row after a reset, not to the suggestion', () => {
    const { result } = renderHook(() => useLineEntry(blank, complete, { item: '7', qty: '40' }))
    act(() => result.current.reset())
    expect(result.current.rows).toEqual([blank])
  })
})
