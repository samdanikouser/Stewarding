import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PriceTrend } from '@/pages/PriceTrend'

const history = {
  item: { code: 'PL-001', name: 'Dinner plate' },
  summary: { count: 3, first: 1.5, latest: 4, lowest: 1.5, highest: 4, average: 3.4, change_pct: 166.7 },
  points: [
    { date: '2025-12-01', price: 1.5, qty: 10, supplier: 'Gulf Catering', invoice: 'P-0', change_pct: null },
    { date: '2026-01-10', price: 2, qty: 10, supplier: 'Gulf Catering', invoice: 'P-1', change_pct: 33.3 },
    { date: '2026-02-10', price: 4, qty: 30, supplier: 'Metro Foods', invoice: 'P-2', change_pct: 100 },
  ],
}
vi.mock('@/lib/useApi', () => ({ qs: () => '', useApi: () => ({ data: history, error: null, reload: vi.fn() }) }))

describe('PriceTrend', () => {
  it('shows the summary, a line over the invoices and each invoice with its change', () => {
    render(<PriceTrend item={{ id: 1, code: 'PL-001', name: 'Dinner plate' }} onClose={vi.fn()} />)
    expect(screen.getByRole('img', { name: /Price from 1.500 to 4.000 over 3 invoices/ })).toBeTruthy()
    expect(screen.getByText('+166.7%')).toBeTruthy()          // since the first invoice
    expect(screen.getByText('+100%')).toBeTruthy()            // the latest jump
    expect(screen.getByText('Metro Foods')).toBeTruthy()
  })
})
