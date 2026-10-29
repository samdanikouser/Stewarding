import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ActionMenu } from '@/components/ui/action-menu'

function setup() {
  const onFace = vi.fn()
  const onDelete = vi.fn()
  render(
    <ActionMenu
      label="More actions for Sid"
      actions={[
        { label: 'Enroll face', onClick: onFace },
        { label: 'Reset password', onClick: vi.fn(), hidden: true },
        { label: 'Delete employee', onClick: onDelete, tone: 'danger' },
      ]}
    />,
  )
  return { onFace, onDelete, user: userEvent.setup(), button: screen.getByRole('button', { name: 'More actions for Sid' }) }
}

describe('ActionMenu', () => {
  it('stays closed until opened, then lists only the actions that are not hidden', async () => {
    const { user, button } = setup()
    expect(screen.queryByRole('menu')).toBeNull()
    await user.click(button)
    expect(screen.getAllByRole('menuitem').map((i) => i.textContent?.trim())).toEqual(['Enroll face', 'Delete employee'])
    expect(button.getAttribute('aria-expanded')).toBe('true')
  })

  it('runs the chosen action and closes', async () => {
    const { user, button, onDelete, onFace } = setup()
    await user.click(button)
    await user.click(screen.getByRole('menuitem', { name: 'Delete employee' }))
    expect(onDelete).toHaveBeenCalledTimes(1)
    expect(onFace).not.toHaveBeenCalled()
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('closes on Escape and on a click outside, and moves between items with the arrow keys', async () => {
    const { user, button } = setup()
    await user.click(button)
    await user.keyboard('{ArrowDown}')
    expect(document.activeElement?.textContent?.trim()).toBe('Delete employee')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    await user.click(button)
    await user.click(document.body)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('can show a word beside the dots so the menu is easy to find', () => {
    render(<ActionMenu label="More actions for Sam" text="More" actions={[{ label: 'Delete', onClick: () => undefined }]} />)
    expect(screen.getByRole('button', { name: 'More actions for Sam' }).textContent).toBe('More')
  })
})

