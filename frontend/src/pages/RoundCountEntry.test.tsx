import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RoundCountEntry } from '@/pages/RoundCountEntry'

const put = vi.fn().mockResolvedValue({ saved: 1, refused: [], needs_reason: [] })
vi.mock('@/lib/api', () => ({ api: (...a: unknown[]) => put(...a) }))
vi.mock('@/lib/toast', () => ({ useRun: () => async (f: () => Promise<unknown>) => { await f(); return true } }))
vi.mock('@/lib/useApi', () => ({
  qs: () => '',
  useApi: () => ({ reload: vi.fn(), data: { status: 'open', round_status: 'counting', items: [
    { item_id: 1, code: 'P1', name: 'Plate', unit: 'pc', category: 'Ware', storage_location: null, qty: null, reason: '', others: 0, received: 10, book: 10, allowance: 10, here: 5 },
  ] } }),
}))

describe('RoundCountEntry saving', () => {
  it('warns about unsaved numbers, saves on the Save button and then says so', async () => {
    render(<RoundCountEntry roundId={1} locationId={2} locationName="Bar" onBack={() => {}} />)
    fireEvent.change(screen.getByLabelText('Counted Plate'), { target: { value: '4' } })
    expect(screen.getByText(/not saved yet/)).toBeTruthy()
    const leave = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(leave)
    expect(leave.defaultPrevented).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.getByText(/All changes saved/)).toBeTruthy())
    expect(put).toHaveBeenCalledWith('/rounds/1/counts/2', { method: 'PUT', body: { entries: { 1: { qty: '4', reason: '' } } } })
  })
})
