import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Item } from '@/lib/useItems'
import { MinimumCell } from '@/pages/MinimumCell'

const api = vi.hoisted(() => vi.fn().mockResolvedValue({}))
vi.mock('@/lib/api', () => ({ api }))
vi.mock('@/lib/toast', () => ({ useRun: () => async (fn: () => Promise<unknown>) => { await fn(); return true } }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ me: { locations: [{ id: 1, name: 'Main Kitchen' }, { id: 2, name: 'Banquet Hall' }] } }) }))

const item = {
  id: 9, name: 'Side Plate', min_level: 40, minimum: 40, location_minimums: {},
  short_at: [{ location_id: 1, qty: 12, minimum: 40 }],
} as unknown as Item

beforeEach(() => api.mockClear())

describe('MinimumCell', () => {
  it('lists the places that fall short when no location is chosen', () => {
    render(<MinimumCell item={item} locationId={null} canEdit onSaved={() => {}} />)
    expect(screen.getByText('Main Kitchen: 12 of 40')).toBeInTheDocument()
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
  })

  it('saves a new minimum for the chosen location when the box is left', async () => {
    const saved = vi.fn()
    render(<MinimumCell item={item} locationId={1} canEdit onSaved={saved} />)
    const box = screen.getByLabelText('Minimum for Side Plate')
    fireEvent.change(box, { target: { value: '150' } })
    fireEvent.blur(box)
    await waitFor(() => expect(saved).toHaveBeenCalled())
    expect(api).toHaveBeenCalledWith('/inventory/items/9/levels/1', { method: 'PUT', body: { min_level: 150 } })
  })

  it('goes back to the item default when the box is emptied', async () => {
    render(<MinimumCell item={{ ...item, minimum: 150, location_minimums: { 1: 150 } }} locationId={1} canEdit onSaved={() => {}} />)
    expect(screen.getByText('set for this location')).toBeInTheDocument()
    const box = screen.getByLabelText('Minimum for Side Plate')
    fireEvent.change(box, { target: { value: '' } })
    fireEvent.blur(box)
    await waitFor(() => expect(api).toHaveBeenCalledWith('/inventory/items/9/levels/1', { method: 'PUT', body: { min_level: null } }))
  })

  it('does not call the server when nothing changed, and shows no box without permission', () => {
    const { rerender } = render(<MinimumCell item={item} locationId={1} canEdit onSaved={() => {}} />)
    const box = screen.getByLabelText('Minimum for Side Plate')
    fireEvent.blur(box)
    expect(api).not.toHaveBeenCalled()
    rerender(<MinimumCell item={item} locationId={1} canEdit={false} onSaved={() => {}} />)
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument()
  })
})
