import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsRules } from '@/pages/settings/SettingsRules'

const mocks = vi.hoisted(() => ({ reload: vi.fn(), api: vi.fn(async () => ({})) }))
vi.mock('@/lib/useApi', () => ({
  useApi: () => ({
    data: {
      settings: { 'attendance.face_required': 0, 'attendance.face_liveness': 1, 'attendance.missed_checkout_hours': 16, 'attendance.missed_checkout_after_shift_hours': 2, 'attendance.max_accuracy_m': 100, 'attendance.snapshot_days': 90, 'attendance.face_match_max': 45, 'breakage.approval_qty': 5 },
      limits: { 'attendance.face_required': [0, 1], 'attendance.face_liveness': [0, 1], 'attendance.missed_checkout_hours': [1, 72], 'attendance.missed_checkout_after_shift_hours': [0, 24], 'attendance.max_accuracy_m': [0, 5000], 'attendance.snapshot_days': [0, 3650], 'attendance.face_match_max': [10, 80], 'breakage.approval_qty': [0, 100000] },
    },
    reload: mocks.reload,
  }),
}))
vi.mock('@/lib/api', () => ({ api: mocks.api }))
vi.mock('@/lib/toast', () => ({ useRun: () => async (action: () => Promise<unknown>) => (await action(), true) }))

describe('SettingsRules', () => {
  beforeEach(() => {
    mocks.api.mockClear()
    mocks.reload.mockClear()
  })

  it('shows the switches and the numbers with their units for its own topic only', () => {
    render(<SettingsRules section="attendance" />)
    expect(screen.getByRole('heading', { name: 'Check-in and attendance rules' })).toBeTruthy()
    expect(screen.getByRole('switch', { name: /Require face verification/ }).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole('switch', { name: /Live head-turn/ }).getAttribute('aria-checked')).toBe('true')
    expect((screen.getByLabelText(/Missed check-out after/) as HTMLInputElement).value).toBe('16')
    expect(screen.getAllByText('hours').length).toBe(2)
    expect(screen.queryByText(/Approval needed from this quantity/)).toBeNull()
    expect(screen.queryByRole('region', { name: 'Unsaved changes' })).toBeNull()
  })

  it('counts unsaved changes, can discard them, and saves only what changed', async () => {
    const user = userEvent.setup()
    render(<SettingsRules section="attendance" />)
    await user.click(screen.getByRole('switch', { name: /Require face verification/ }))
    expect(screen.getByText('1 unsaved change')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Discard' }))
    expect(screen.queryByRole('region', { name: 'Unsaved changes' })).toBeNull()
    expect(screen.getByRole('switch', { name: /Require face verification/ }).getAttribute('aria-checked')).toBe('false')

    await user.click(screen.getByRole('switch', { name: /Require face verification/ }))
    const hours = screen.getByLabelText(/Missed check-out after/)
    await user.clear(hours)
    await user.type(hours, '24')
    expect(screen.getByText('2 unsaved changes')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(mocks.api).toHaveBeenCalledWith('/settings', { method: 'PUT', body: { values: { 'attendance.face_required': 1, 'attendance.missed_checkout_hours': 24 } } })
    expect(mocks.reload).toHaveBeenCalledTimes(1)
  })

  it('refuses a number outside its limits and says why', async () => {
    const user = userEvent.setup()
    render(<SettingsRules section="attendance" />)
    const match = screen.getByLabelText(/Face match limit/)
    await user.clear(match)
    await user.type(match, '95')
    expect(screen.getByRole('alert').textContent).toBe('Enter a whole number from 10 to 80')
    expect((screen.getByRole('button', { name: 'Save changes' }) as HTMLButtonElement).disabled).toBe(true)
    await user.clear(match)
    expect((screen.getByRole('button', { name: 'Save changes' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
