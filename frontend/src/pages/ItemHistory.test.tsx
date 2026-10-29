import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ItemHistory } from '@/pages/ItemHistory'

const story = {
  item: { id: 8, code: 'PL-001', name: 'Dinner plate', unit: 'Each' }, opening_balance: 0, closing: 416, received_net: 430, on_hand_now: 416, adds_up: true, total: 3,
  totals: [{ kind: 'received', label: 'Received on invoices', qty: 430 }, { kind: 'breakage', label: 'Breakage', qty: -3 }, { kind: 'count_adjustment', label: 'Physical count adjustments', qty: -11 }],
  rows: [
    { id: 3, at: '2026-03-02T08:00:00Z', location: 'Main Kitchen', kind: 'count_adjustment', label: 'Physical count adjustments', qty: -11, balance: 416, document: 'Physical count #4', reason: 'Physical count #4 variance', by: 'Maya' },
    { id: 2, at: '2026-03-01T08:00:00Z', location: 'Main Kitchen', kind: 'breakage', label: 'Breakage', qty: -3, balance: 427, document: 'Breakage report BRK-1', reason: 'dropped', by: 'Sam' },
    { id: 1, at: '2026-02-01T08:00:00Z', location: 'Main Kitchen', kind: 'received', label: 'Received on invoices', qty: 430, balance: 430, document: 'Invoice A-1 (Gulf)', reason: null, by: 'Maya' },
  ],
}
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ me: { locations: [{ id: 1, name: 'Main Kitchen' }] } }) }))
const asked = vi.hoisted(() => [] as string[])
vi.mock('@/lib/useApi', () => ({
  qs: (p: Record<string, unknown>) => `?${Object.entries(p).filter(([, v]) => v !== null && v !== '' && v !== undefined).map(([k, v]) => `${k}=${v}`).join('&')}`,
  useApi: (path: string) => { asked.push(path); return { data: story, error: null, reload: vi.fn() } },
}))

describe('ItemHistory', () => {
  it('shows what was received apart from the adjustments, a running balance, and that it matches what is on hand', () => {
    render(<ItemHistory item={{ id: 8, code: 'PL-001', name: 'Dinner plate' }} onClose={vi.fn()} />)
    expect(screen.getByText('Received (net of voids and returns)')).toBeTruthy()
    expect(screen.getAllByText('Physical count adjustments').length).toBeGreaterThan(0)
    expect(screen.getByText('Physical count #4')).toBeTruthy()
    expect(screen.getByText('Matches what is on hand')).toBeTruthy()
  })

  it('has a This year button that asks for 1 January to today, and always shows the year so far beside the totals', () => {
    render(<ItemHistory item={{ id: 8, code: 'PL-001', name: 'Dinner plate' }} onClose={vi.fn()} />)
    expect(screen.getByLabelText('Year to date').textContent).toContain('received 430')
    fireEvent.click(screen.getByRole('button', { name: 'This year' }))
    const year = `${new Date().getFullYear()}-01-01`
    expect(asked.some((p) => p.includes(`date_from=${year}`) && !p.includes('size=1'))).toBe(true)
    expect(screen.getByRole('button', { name: 'This year' }).getAttribute('aria-pressed')).toBe('true')
  })
})
