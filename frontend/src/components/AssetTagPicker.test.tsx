import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { AssetTagPicker } from '@/components/AssetTagPicker'

vi.mock('@/lib/useApi', () => ({
  qs: (p: Record<string, unknown>) => `?${Object.entries(p).map(([k, v]) => `${k}=${v}`).join('&')}`,
  useApi: () => ({ data: [{ id: 1, asset_tag: 'KN-MK-01', condition: 'good' }, { id: 2, asset_tag: 'KN-MK-02', condition: 'damaged' }, { id: 3, asset_tag: 'KN-MK-03', condition: 'good' }] }),
}))

function Harness({ qty }: { qty: number }) {
  const [ids, setIds] = useState<number[]>([])
  return <AssetTagPicker itemId={9} locationId={1} qty={qty} value={ids} onChange={setIds} />
}

describe('AssetTagPicker', () => {
  it('lets exactly the quantity be ticked and shows how many are chosen', async () => {
    const user = userEvent.setup()
    render(<Harness qty={2} />)
    expect(screen.getByText('Asset tags moving (0 of 2 chosen)')).toBeTruthy()
    await user.click(screen.getByLabelText('KN-MK-01'))
    await user.click(screen.getByLabelText(/KN-MK-02/))
    expect(screen.getByText('Asset tags moving (2 of 2 chosen)')).toBeTruthy()
    expect((screen.getByLabelText('KN-MK-03') as HTMLInputElement).disabled).toBe(true)
    await user.click(screen.getByLabelText('KN-MK-01'))
    expect((screen.getByLabelText('KN-MK-03') as HTMLInputElement).disabled).toBe(false)
  })
})
