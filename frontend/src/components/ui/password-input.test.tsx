import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { PasswordInput } from '@/components/ui/password-input'

describe('PasswordInput', () => {
  it('hides what is typed until the button is pressed, and hides it again', async () => {
    const user = userEvent.setup()
    render(<PasswordInput aria-label="Password" defaultValue="hunter2-secret" />)
    const field = screen.getByLabelText('Password') as HTMLInputElement
    expect(field.type).toBe('password')
    await user.click(screen.getByRole('button', { name: 'Show password' }))
    expect(field.type).toBe('text')
    expect(screen.getByRole('button', { name: 'Hide password' }).getAttribute('aria-pressed')).toBe('true')
    await user.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(field.type).toBe('password')
  })
})
