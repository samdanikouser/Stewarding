import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsRoles } from '@/pages/settings/SettingsRoles'

const mocks = vi.hoisted(() => ({ reload: vi.fn(), api: vi.fn(async () => ({})) }))
const roles = [
  { id: 1, name: 'manager', label: 'Back of House Manager', tier: 'manager', builtin: true, permissions: ['a', 'b', 'c'], users: 1, defaults: null },
  { id: 2, name: 'steward', label: 'Steward', tier: 'steward', builtin: true, permissions: ['a'], users: 4, defaults: ['a'] },
  { id: 3, name: 'butcher', label: 'Butcher', tier: 'steward', builtin: false, permissions: ['a'], users: 2, defaults: null },
  { id: 4, name: 'spare', label: 'Spare role', tier: 'supervisor', builtin: false, permissions: ['a', 'b'], users: 0, defaults: null },
]
const catalog = { tiers: ['supervisor', 'steward'], groups: [{ group: 'General', permissions: [{ key: 'a', label: 'See a' }, { key: 'b', label: 'See b' }, { key: 'c', label: 'See c' }] }] }

vi.mock('@/lib/useApi', () => ({ useApi: (path: string) => ({ data: path === '/roles' ? roles : catalog, reload: mocks.reload }) }))
vi.mock('@/lib/api', () => ({ api: mocks.api }))
vi.mock('@/lib/toast', () => ({ useRun: () => async (action: () => Promise<unknown>) => (await action(), true) }))

const card = (name: string) => screen.getByRole('heading', { name }).closest('div[class*="rounded-2xl"]') as HTMLElement

describe('SettingsRoles', () => {
  beforeEach(() => {
    mocks.api.mockClear()
    mocks.reload.mockClear()
  })

  it('shows Delete on every card but only allows it for a custom role nobody holds', () => {
    render(<SettingsRoles />)
    const button = (name: string) => within(card(name)).getByRole('button', { name: /Delete/ }) as HTMLButtonElement
    expect(button('Back of House Manager').disabled).toBe(true)
    expect(button('Back of House Manager').title).toBe('Built-in roles cannot be deleted')
    expect(button('Steward').disabled).toBe(true)
    expect(button('Butcher').disabled).toBe(true)
    expect(button('Butcher').title).toBe('Move the 2 people with this role to another role first')
    expect(button('Spare role').disabled).toBe(false)
  })

  it('deletes an unused custom role after confirming', async () => {
    const user = userEvent.setup()
    render(<SettingsRoles />)
    await user.click(within(card('Spare role')).getByRole('button', { name: /Delete/ }))
    expect(mocks.api).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Delete role' }))
    expect(mocks.api).toHaveBeenCalledWith('/roles/4', { method: 'DELETE' })
    expect(mocks.reload).toHaveBeenCalledTimes(1)
  })

  it('lets any role be copied but not the manager role edited', async () => {
    const user = userEvent.setup()
    render(<SettingsRoles />)
    expect(within(card('Back of House Manager')).queryByRole('button', { name: /Edit/ })).toBeNull()
    await user.click(within(card('Steward')).getByRole('button', { name: /Copy/ }))
    expect((screen.getByLabelText('Role name') as HTMLInputElement).value).toBe('Steward copy')
    expect(screen.getByText('1 of 3 permissions chosen')).toBeTruthy()
  })
})
