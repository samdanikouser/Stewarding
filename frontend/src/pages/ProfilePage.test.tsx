import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProfilePage } from '@/pages/ProfilePage'

const mocks = vi.hoisted(() => ({
  profile: null as unknown,
  reload: vi.fn(),
  api: vi.fn(async () => ({ access_token: 'fresh-token' })),
  setToken: vi.fn(),
}))
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ me: { modules: [{ key: 'dashboard', label: 'Dashboard' }, { key: 'roster', label: 'Roster' }] }, logout: vi.fn(), changePassword: vi.fn() }),
}))
vi.mock('@/lib/useApi', () => ({ useApi: () => ({ data: mocks.profile, reload: mocks.reload }) }))
vi.mock('@/lib/api', () => ({ api: mocks.api, tokenStore: { set: mocks.setToken } }))
vi.mock('@/lib/toast', () => ({ useRun: () => async (action: () => Promise<unknown>) => (await action(), true) }))

const employee = {
  code: 'E004', full_name: 'Sid Steward', job_title: 'Steward', company: 'Example Kitchens', status: 'active',
  phone: '+965 5000 1234', emergency_contact: 'Sara', date_joined: '2025-01-12', supervisor: 'Sam Supervisor', locations: ['Main Kitchen'],
}

function show() {
  render(<MemoryRouter><ProfilePage /></MemoryRouter>)
  return userEvent.setup()
}

describe('ProfilePage', () => {
  beforeEach(() => {
    mocks.api.mockClear()
    mocks.reload.mockClear()
    mocks.profile = { email: 'sid@example.test', role_label: 'Steward', last_login_at: null, employee }
  })

  it('shows the person, their details and the modules they can open', () => {
    show()
    expect(screen.getByText('Sid Steward')).toBeTruthy()
    expect(screen.getByText(/sid@example.test · E004/)).toBeTruthy()
    expect(screen.getByText('Sam Supervisor')).toBeTruthy()
    expect(screen.getByText('Main Kitchen')).toBeTruthy()
    expect(screen.getByText('Roster')).toBeTruthy()
  })

  it('keeps Save changes off until the phone or emergency contact changes, then saves them trimmed', async () => {
    const user = show()
    const save = screen.getByRole('button', { name: 'Save changes' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    const phone = screen.getByLabelText('Phone')
    await user.clear(phone)
    await user.type(phone, ' +965 5000 9999 ')
    expect(save.disabled).toBe(false)
    await user.click(save)
    expect(mocks.api).toHaveBeenCalledWith('/profile', { method: 'PUT', body: { phone: '+965 5000 9999', emergency_contact: 'Sara' } })
    expect(mocks.reload).toHaveBeenCalledTimes(1)
  })

  it('asks before signing out other devices, then keeps this device signed in with a fresh token', async () => {
    mocks.setToken.mockClear()
    const user = show()
    await user.click(screen.getByRole('button', { name: 'Sign out other devices' }))
    expect(mocks.api).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Sign them out' }))
    expect(mocks.api).toHaveBeenCalledWith('/auth/sign-out-others', { method: 'POST' })
    expect(mocks.setToken).toHaveBeenCalledWith('fresh-token')
  })

  it('leaves other devices alone when the question is cancelled', async () => {
    const user = show()
    await user.click(screen.getByRole('button', { name: 'Sign out other devices' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(mocks.api).not.toHaveBeenCalled()
  })

  it('shows no details form for an account that has no employee record', () => {
    mocks.profile = { email: 'orphan@example.test', role_label: 'Steward', last_login_at: null, employee: null }
    show()
    expect(screen.getByText('orphan@example.test')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Save changes' })).toBeNull()
  })
})
