import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CheckInPage } from '@/pages/CheckInPage'

const mocks = vi.hoisted(() => ({ days: null as unknown, canManage: false }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ me: { permissions: mocks.canManage ? ['settings.manage'] : [] } }) }))
vi.mock('@/lib/useApi', () => ({ useApi: () => ({ data: mocks.days, reload: vi.fn() }) }))
vi.mock('@/pages/MyShiftCard', () => ({ MyShiftCard: () => <p>Check in card</p> }))

describe('CheckInPage', () => {
  beforeEach(() => {
    mocks.canManage = false
    mocks.days = { items: [
      { id: 1, local_date: '2026-10-22', check_in_at: '2026-10-22T05:00:00', check_out_at: '2026-10-22T13:00:00', late_minutes: 12, payable_minutes: 480, open: false, missed_checkout: false },
      { id: 2, local_date: '2026-10-23', check_in_at: '2026-10-23T05:00:00', check_out_at: null, late_minutes: 0, payable_minutes: null, open: true, missed_checkout: false },
    ] }
  })

  it('shows the check-in card first and the last days beneath it, with the open day marked', () => {
    render(<MemoryRouter><CheckInPage /></MemoryRouter>)
    expect(screen.getByRole('heading', { name: 'Check in & out' })).toBeTruthy()
    expect(screen.getByText('Check in card')).toBeTruthy()
    expect(screen.getByText('Late 12m')).toBeTruthy()
    expect(screen.getByText('8h 0m')).toBeTruthy()
    expect(screen.getByText('Now')).toBeTruthy()
    expect(screen.getByRole('link', { name: /All attendance and leave/ }).getAttribute('href')).toBe('/attendance')
  })

  it('links managers to the check-in rules and shows nobody else the link', () => {
    mocks.canManage = true
    const { unmount } = render(<MemoryRouter><CheckInPage /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'Check-in rules' }).getAttribute('href')).toBe('/settings/attendance')
    unmount()
    mocks.canManage = false
    render(<MemoryRouter><CheckInPage /></MemoryRouter>)
    expect(screen.queryByRole('link', { name: 'Check-in rules' })).toBeNull()
  })

  it('says so when there is no attendance yet', () => {
    mocks.days = { items: [] }
    render(<MemoryRouter><CheckInPage /></MemoryRouter>)
    expect(screen.getByText('No attendance yet')).toBeTruthy()
  })
})
