import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { UserMenu } from '@/components/UserMenu'

const auth = vi.hoisted(() => ({
  me: { email: 'maya@example.test', role_label: 'Back of House Manager', employee: { name: 'Maya Manager' } },
  logout: vi.fn(),
}))
vi.mock('@/lib/auth', () => ({ useAuth: () => auth }))

function setup() {
  const onNavigate = vi.fn()
  render(<MemoryRouter><UserMenu onNavigate={onNavigate} /></MemoryRouter>)
  return { onNavigate, user: userEvent.setup() }
}

describe('UserMenu', () => {
  it('shows who is signed in and keeps the menu closed until it is clicked', async () => {
    const { user } = setup()
    expect(screen.getByText('Maya Manager')).toBeTruthy()
    expect(screen.queryByRole('menu')).toBeNull()
    await user.click(screen.getByRole('button', { name: /Maya Manager/ }))
    expect(screen.getByRole('menu')).toBeTruthy()
    expect(screen.getByText('maya@example.test')).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: 'My profile' }).getAttribute('href')).toBe('/account')
    expect(screen.getByRole('menuitem', { name: 'Change password' }).getAttribute('href')).toBe('/account#security')
  })

  it('closes on Escape and gives focus back to the profile button', async () => {
    const { user } = setup()
    const trigger = screen.getByRole('button', { name: /Maya Manager/ })
    await user.click(trigger)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })

  it('closes when the page outside it is clicked', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: /Maya Manager/ }))
    await user.click(document.body)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('closes the sidebar drawer when a link is followed and signs out from the menu', async () => {
    const { user, onNavigate } = setup()
    await user.click(screen.getByRole('button', { name: /Maya Manager/ }))
    await user.click(screen.getByRole('menuitem', { name: 'My profile' }))
    expect(onNavigate).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: /Maya Manager/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(auth.logout).toHaveBeenCalledTimes(1)
  })
})
