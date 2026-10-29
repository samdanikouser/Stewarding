import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { LotFamily } from '@/pages/trace/LotFamily'
import type { Lot } from '@/pages/trace/types'

const lot = (over: Partial<Lot>): Lot => ({
  id: 1, code: 'B2610-884', kind: 'received', item: 'AUS Angus beef tenderloin', food_item_id: 1, food_group: 'red_meat', group_label: 'Red meat',
  condition: 'chilled_raw', condition_label: 'Chilled, raw', supplier: 'Al Wazzan', supplier_lot: 'B2610-884', produced_on: null, expiry_on: null, use_by: null,
  past_use_by: false, temp_c: null, qty: 6.7, waste_qty: null, unit: 'kg', pack_count: null, pack_description: null, tag_number: null, location_id: 1,
  location: 'Main Kitchen', status: 'active', note: null, created_by_name: null, created_at: '2026-03-02T02:05:00Z', thawed_at: null, ...over,
})

const family = lot({
  balance: { qty: 6.7, unit: 'kg', portioned: 5, waste: 0.3, left: 1.4, unmeasured: 0 },
  children: [
    lot({ id: 2, code: 'B2610-884-1', kind: 'portion', qty: 4800, unit: 'g', pack_count: 24, pack_description: '200 g Tenderloin steaks', condition: 'vacuum_chilled', condition_label: 'Vacuum chilled' }),
    lot({ id: 3, code: 'B2610-884-2', kind: 'portion', qty: 200, unit: 'g', pack_count: 1, pack_description: '200 g Trim', condition: 'vacuum_chilled', condition_label: 'Vacuum chilled' }),
  ],
})

describe('LotFamily', () => {
  it('shows the delivery with its sub-lots beneath and every amount in the unit that reads best', async () => {
    const open = vi.fn()
    render(<LotFamily lot={family} onOpen={open} />)
    expect(screen.getByText(/6.7 kg received/)).toBeTruthy()
    expect(screen.getByText('Left to portion').nextSibling?.textContent).toBe('1.4 kg')
    expect(screen.getByText('In portions').nextSibling?.textContent).toBe('5 kg')
    expect(screen.getByText('2 sub-lots made from B2610-884')).toBeTruthy()
    expect(screen.getByText(/24 x 200 g Tenderloin steaks/)).toBeTruthy()
    expect(screen.getByText(/= 4.8 kg in all/)).toBeTruthy()
    expect(screen.getByText(/= 200 g in all/)).toBeTruthy()
    await userEvent.setup().click(screen.getByText('B2610-884-1'))
    expect(open).toHaveBeenCalledWith(2)
  })

  it('folds the sub-lots away and back', async () => {
    const user = userEvent.setup()
    render(<LotFamily lot={family} onOpen={() => undefined} />)
    await user.click(screen.getByRole('button', { name: /2 sub-lots made from/ }))
    expect(screen.queryByText('B2610-884-1')).toBeNull()
    await user.click(screen.getByRole('button', { name: /2 sub-lots made from/ }))
    expect(screen.getByText('B2610-884-1')).toBeTruthy()
  })

  it('shows a delivery that has not been portioned without a balance or sub-lots', () => {
    render(<LotFamily lot={lot({ children: [], balance: null })} onOpen={() => undefined} />)
    expect(screen.queryByText('Left to portion')).toBeNull()
    expect(screen.queryByText(/sub-lot/)).toBeNull()
  })
})
