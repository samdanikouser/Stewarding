import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from '@/pages/LoginPage'

const mocks = vi.hoisted(() => ({ login: vi.fn(), api: vi.fn() }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ login: mocks.login }) }))
vi.mock('@/lib/api', () => ({ api: mocks.api }))
vi.mock('@/lib/useApi', () => ({ useApi: () => ({ data: { name: 'Test Kitchens', has_logo: false } }) }))

const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })

describe('LoginPage', () => {
  beforeEach(() => {
    mocks.login.mockReset()
    mocks.api.mockReset()
  })

  it('welcomes people back and signs them in with their email and password', async () => {
    mocks.login.mockResolvedValue(undefined)
    render(<LoginPage />)
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeTruthy()
    expect(screen.getByText('Test Kitchens')).toBeTruthy()
    fill('Email', 'sam@example.test')
    fill('Password', 'a-long-password')
    fireEvent.click(screen.getByRole('button', { name: /^Sign in/ }))
    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith('sam@example.test', 'a-long-password'))
  })

  it('says what went wrong when the sign-in is refused', async () => {
    mocks.login.mockRejectedValue(new Error('Wrong email or password'))
    render(<LoginPage />)
    fill('Email', 'sam@example.test')
    fill('Password', 'nope-nope-nope')
    fireEvent.click(screen.getByRole('button', { name: /^Sign in/ }))
    expect((await screen.findByRole('alert')).textContent).toContain('Wrong email or password')
    expect((screen.getByRole('button', { name: /^Sign in/ }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('switches to a request form that sends the name too, then returns to sign in with a notice', async () => {
    mocks.api.mockResolvedValue({})
    render(<LoginPage />)
    fireEvent.click(screen.getByRole('button', { name: 'New here? Request an account' }))
    expect(screen.getByRole('heading', { name: 'Request an account' })).toBeTruthy()
    fill('Full name', 'Sam Steward')
    fill('Email', 'sam@example.test')
    fill('Password', 'a-long-password')
    fireEvent.click(screen.getByRole('button', { name: /^Request account/ }))
    await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/auth/signup', { body: { full_name: 'Sam Steward', email: 'sam@example.test', password: 'a-long-password' } }))
    expect((await screen.findByRole('status')).textContent).toContain('Request sent')
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeTruthy()
  })

  it('warns when Caps Lock is on while typing the password', () => {
    render(<LoginPage />)
    fireEvent.keyDown(screen.getByLabelText('Password'), { key: 'a', modifierCapsLock: true })
    expect(screen.getByText('Caps Lock is on')).toBeTruthy()
    fireEvent.blur(screen.getByLabelText('Password'))
    expect(screen.queryByText('Caps Lock is on')).toBeNull()
  })
})
