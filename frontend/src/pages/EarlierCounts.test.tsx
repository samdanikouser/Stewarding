import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { EarlierCounts } from '@/pages/EarlierCounts'

vi.mock('@/lib/useItems', () => ({ useAllItems: () => ({ items: [], byId: new Map([[1, { id: 1, name: 'Dinner plate' }]]) }) }))
vi.mock('@/lib/useApi', () => ({
  useApi: (path: string) => ({ data: path === '/stock/counts'
    ? [{ id: 4, location_id: 1, counted_at: '2026-03-02T08:00:00Z', status: 'posted', lines: [{ item_id: 1, system_qty: 40, counted_qty: 37, variance: -3, reason: null }] }]
    : [{ id: 1, name: 'Main Kitchen' }] }),
}))

describe('EarlierCounts', () => {
  it('keeps the old one-location counts on view, read-only, with their variances', () => {
    render(<EarlierCounts />)
    expect(screen.getByText(/Count #4: Main Kitchen/)).toBeTruthy()
    expect(screen.getByText(/variance -3/)).toBeTruthy()
    expect(screen.queryByRole('button')).toBeNull()
  })
})
