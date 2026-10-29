import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ScanPage } from '@/pages/ScanPage'

const mocks = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('@/lib/api', () => ({ api: mocks.api }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ me: { permissions: ['checklist.view', 'temp.view', 'notification.view'] } }) }))

/** The scan answers with `place`; the lists beside it answer with what is waiting there. */
function answer(place: unknown) {
  mocks.api.mockImplementation(async (path: string) => {
    if (path === '/scan') return place
    if (path.startsWith('/checklists/instances')) return { items: [
      { id: 1, description: 'Wipe the pass', effective_status: 'overdue', due_at: '2026-03-02T05:00:00Z', local_date: '2026-03-02' },
      { id: 2, description: 'Sign off the day', effective_status: 'completed', due_at: null, local_date: '2026-03-02' }] }
    if (path.startsWith('/monitoring/due')) return [{ equipment_id: 7, equipment: 'Walk-in fridge', schedule_id: 3, slot_at: '2026-03-02T08:00:00Z', status: 'due' }]
    if (path.startsWith('/notifications')) return { unread: 2, items: [{ id: 9, title: 'Fridge check due', priority: 'high', link: '/monitoring', action_needed: false }] }
    return null
  })
}

function Landed() {
  const { pathname, state } = useLocation()
  return <p data-testid="landed">{pathname} {JSON.stringify(state)}</p>
}

function visit() {
  render(
    <MemoryRouter initialEntries={['/scan/e7.sig']}>
      <Routes>
        <Route path="scan/:token" element={<ScanPage />} />
        <Route path="*" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ScanPage', () => {
  it('confirms a monitoring point and opens its form at the right place', async () => {
    answer({ kind: 'equipment', id: 7, name: 'Walk-in fridge', location_id: 2, location_name: 'Main kitchen' })
    visit()
    expect(await screen.findByText('Walk-in fridge')).toBeTruthy()
    expect(mocks.api).toHaveBeenCalledWith('/scan', { body: { token: 'e7.sig' } })
    await userEvent.setup().click(screen.getByRole('button', { name: 'Record a check' }))
    expect(screen.getByTestId('landed').textContent).toBe('/monitoring {"locationId":2,"equipmentId":7}')
  })

  it('opens the checklists for a scanned location', async () => {
    answer({ kind: 'location', id: 2, name: 'Main kitchen', location_id: 2, location_name: 'Main kitchen' })
    visit()
    await userEvent.setup().click(await screen.findByRole('button', { name: "Open today's checklists" }))
    expect(screen.getByTestId('landed').textContent).toContain('/checklists')
  })

  it('shows what is waiting at the place: open tasks, checks and unread alerts', async () => {
    answer({ kind: 'location', id: 2, name: 'Main kitchen', location_id: 2, location_name: 'Main kitchen' })
    visit()
    expect(await screen.findByText('Wipe the pass')).toBeTruthy()
    expect(screen.queryByText('Sign off the day')).toBeNull()                 // already done: not waiting
    expect(await screen.findByText('1 overdue', { exact: false }, )).toBeTruthy()
    expect(await screen.findByText('Fridge check due')).toBeTruthy()          // an alert for this person
    expect(screen.getAllByText('Walk-in fridge').length).toBeGreaterThan(0)   // a check waiting
    expect(mocks.api).toHaveBeenCalledWith(expect.stringContaining('/checklists/instances?location_id=2'))
  })

  it('says why a code was refused', async () => {
    mocks.api.mockRejectedValueOnce(new Error('This is not a QR code from this system'))
    visit()
    expect((await screen.findByRole('alert')).textContent).toBe('This is not a QR code from this system')
  })
})
