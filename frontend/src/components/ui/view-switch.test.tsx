import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ViewSwitch } from '@/components/ui/view-switch'
import { useViewMode } from '@/lib/viewMode'

function Harness() {
  const [mode, choose] = useViewMode('test-list')
  return <><ViewSwitch value={mode} onChange={choose} /><output data-testid="mode">{mode}</output></>
}

describe('ViewSwitch', () => {
  beforeEach(() => localStorage.clear())

  it('starts on cards, switches views and remembers the choice', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<Harness />)
    expect(screen.getByTestId('mode').textContent).toBe('cards')
    await user.click(screen.getByRole('button', { name: 'List' }))
    expect(screen.getByTestId('mode').textContent).toBe('list')
    expect(screen.getByRole('button', { name: 'List' }).getAttribute('aria-pressed')).toBe('true')
    unmount()
    render(<Harness />)
    expect(screen.getByTestId('mode').textContent).toBe('list')
  })

  it('ignores a saved value that is not a view', () => {
    localStorage.setItem('plato.view.test-list', 'carousel')
    render(<Harness />)
    expect(screen.getByTestId('mode').textContent).toBe('cards')
  })
})
