import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SchedulePage } from '@/pages/SchedulePage'

const days = [
  { date: '2026-03-01', shifts: [{ name: 'Week off', start: '00:00', end: '00:00', week_off: true, location: 'Main kitchen' }], leave: null, worked: [], outcome: null },
  { date: '2026-03-02', shifts: [{ name: 'Morning', start: '06:00', end: '14:00', week_off: false, location: 'Main kitchen' }], leave: null, worked: [{ check_in_at: '2026-03-02T02:20:00Z', check_out_at: '2026-03-02T10:00:00Z', late_minutes: 15, open: false }], outcome: 'late' },
  { date: '2026-03-03', shifts: [{ name: 'Night', start: '22:00', end: '06:00', week_off: false, location: 'Main kitchen' }], leave: null, worked: [], outcome: 'missed' },
  { date: '2026-03-04', shifts: [], leave: 'sick_leave', worked: [], outcome: null },
  { date: '2026-03-05', shifts: [], leave: null, worked: [], outcome: null },
]
vi.mock('@/lib/useApi', () => ({
  qs: (p: Record<string, unknown>) => (p.month ? `?month=${p.month}` : ''),
  useApi: () => ({ data: { month: '2026-03', today: '2026-03-02', days }, error: null, reload: vi.fn() }),
}))

describe('SchedulePage', () => {
  it('shows the month as a calendar and tells what a tapped day holds', () => {
    render(<SchedulePage />)
    expect(screen.getByText('March 2026')).toBeTruthy()
    expect(screen.getByRole('button', { name: /, Morning, Worked, arrived late$/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /, Sick leave$/ })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /, Night, No check-in recorded$/ }))
    expect(screen.getByRole('region', { name: 'Selected day' }).textContent).toContain('22:00 to 06:00')
    fireEvent.click(screen.getByRole('button', { name: /, Morning, Worked, arrived late$/ }))
    expect(screen.getByRole('region', { name: 'Selected day' }).textContent).toContain('15 min late')
  })

  it('lists only the days that have something, with the times', () => {
    render(<SchedulePage />)
    fireEvent.click(screen.getByRole('tab', { name: 'List view' }))
    expect(screen.getByText('06:00 - 14:00')).toBeTruthy()
    expect(screen.getByText('Sick leave')).toBeTruthy()
    expect(screen.getAllByRole('listitem')).toHaveLength(4)                 // the empty 5th day is left out
  })
})

describe('SchedulePage week', () => {
  it('starts the week on Sunday: 1 March 2026 is a Sunday, so the grid has no blank cells before it', () => {
    const { container } = render(<SchedulePage />)
    expect(container.querySelectorAll('li[aria-hidden]').length).toBe(0)
    expect([...container.querySelectorAll('[aria-hidden] span')].map((s) => s.textContent).join('')).toBe('SMTWTFS')
  })
})
