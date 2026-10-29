import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { AuthProvider, useAuth } from '@/lib/auth'

function Probe() {
  const { logout } = useAuth()
  return (
    <>
      <p data-testid="path">{useLocation().pathname}</p>
      <button onClick={logout}>Sign out</button>
    </>
  )
}

describe('AuthProvider', () => {
  it('goes back to the start when someone signs out, so the next person does not land on their page', () => {
    render(<MemoryRouter initialEntries={['/stock-movements']}><AuthProvider><Probe /></AuthProvider></MemoryRouter>)
    expect(screen.getByTestId('path').textContent).toBe('/stock-movements')
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(screen.getByTestId('path').textContent).toBe('/')
  })
})
