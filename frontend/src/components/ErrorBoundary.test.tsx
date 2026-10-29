import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from '@/components/ErrorBoundary'

let broken = true
function Fragile() {
  if (broken) throw new Error('Cannot read properties of undefined')
  return <p>All good</p>
}

describe('ErrorBoundary', () => {
  it('shows what went wrong instead of a blank page, and recovers on Try again', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    render(<ErrorBoundary><Fragile /></ErrorBoundary>)
    expect(screen.getByRole('alert').textContent).toContain('Cannot read properties of undefined')
    broken = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('All good')).toBeTruthy()
  })
})
