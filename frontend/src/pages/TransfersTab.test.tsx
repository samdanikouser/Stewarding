import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TransfersTab } from '@/pages/TransfersTab'

const mocks = vi.hoisted(() => ({ api: vi.fn(async () => ({})) }))
vi.mock('@/lib/api', () => ({ api: mocks.api }))
vi.mock('@/lib/toast', () => ({ useRun: () => async (action: () => Promise<unknown>) => (await action(), true) }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ me: { id: 1, permissions: ['stock.approve'], locations: [{ id: 1, name: 'Main Kitchen' }] } }) }))
vi.mock('@/lib/useItems', () => ({
  useAllItems: () => {
    const items = [{ id: 7, code: 'KN-001', name: 'Chef Knife', is_tracked_asset: true }, { id: 8, code: 'PL-001', name: 'Plate', is_tracked_asset: false }]
    return { items, byId: new Map(items.map((i) => [i.id, i])) }
  },
}))
vi.mock('@/lib/useApi', () => ({
  qs: (p: Record<string, unknown>) => `?${Object.entries(p).map(([k, v]) => `${k}=${v}`).join('&')}`,
  useApi: (path: string | null) => ({
    reload: () => undefined,
    data: !path ? null : path.startsWith('/stock/transfers') ? []
      : path.startsWith('/stock/locations') ? [{ id: 1, name: 'Main Kitchen' }, { id: 2, name: 'Banquet Hall' }]
      : path.startsWith('/stock/location-stock') ? [{ item_id: 7, qty: 5, avg_cost: 20 }, { item_id: 8, qty: 50, avg_cost: 2 }]
      : [{ id: 31, asset_tag: 'KN-MK-01', condition: 'good' }, { id: 32, asset_tag: 'KN-MK-02', condition: 'good' }],
  }),
}))

describe('TransfersTab', () => {
  beforeEach(() => mocks.api.mockClear())

  it('asks for the asset tags of a tracked item before the transfer can be made, and sends them', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><TransfersTab /></MemoryRouter>)
    await user.selectOptions(screen.getByLabelText('To'), '2')
    await user.type(screen.getByRole('combobox', { name: 'Item' }), 'knife')
    await user.click(await screen.findByRole('option', { name: /Chef Knife/ }))
    await user.type(screen.getByLabelText('Quantity'), '1')
    const go = screen.getByRole('button', { name: 'Transfer now' }) as HTMLButtonElement
    expect(go.disabled).toBe(true)
    await user.click(screen.getByLabelText('KN-MK-02'))
    expect(go.disabled).toBe(false)
    await user.click(go)
    expect(mocks.api).toHaveBeenCalledWith('/stock/transfers', { body: { from_location_id: 1, to_location_id: 2, note: null, lines: [{ item_id: 7, qty: 1, asset_ids: [32] }] } })
  })

  it('needs no tags for an ordinary item', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><TransfersTab /></MemoryRouter>)
    await user.selectOptions(screen.getByLabelText('To'), '2')
    await user.type(screen.getByRole('combobox', { name: 'Item' }), 'plate')
    await user.click(await screen.findByRole('option', { name: /Plate/ }))
    await user.type(screen.getByLabelText('Quantity'), '3')
    expect(screen.queryByText(/Asset tags moving/)).toBeNull()
    expect((screen.getByRole('button', { name: 'Transfer now' }) as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('TransfersTab catch-up', () => {
  it('records a move that already happened, on the chosen date, from a pasted list', async () => {
    mocks.api.mockClear()
    const user = userEvent.setup()
    render(<MemoryRouter><TransfersTab /></MemoryRouter>)
    await user.selectOptions(screen.getByLabelText('To'), '2')
    await user.click(screen.getByRole('button', { name: 'Paste a list' }))
    await user.type(screen.getByLabelText('Pasted list'), 'PL-001 12{enter}pl-001, 3{enter}NOPE 4')
    await user.click(screen.getByRole('button', { name: 'Add these lines' }))
    expect(screen.getByText(/1 line\(s\) added\. Not understood: NOPE/)).toBeTruthy()      // the same code twice is one line of 15
    await user.click(screen.getByLabelText(/already moved/))
    fireEvent.change(screen.getByLabelText('Date it was moved'), { target: { value: '2026-02-20' } })
    await user.click(screen.getByRole('button', { name: 'Record the move' }))
    expect(mocks.api).toHaveBeenCalledWith('/stock/transfers', { body: { from_location_id: 1, to_location_id: 2, note: null, moved_on: '2026-02-20',
      lines: [{ item_id: 8, qty: 15, asset_ids: [] }] } })
  })
})
