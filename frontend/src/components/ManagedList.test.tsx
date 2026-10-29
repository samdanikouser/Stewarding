import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ManagedList } from '@/components/ManagedList'

function setup() {
  const handlers = {
    onAdd: vi.fn(async () => true),
    onRename: vi.fn(async () => true),
    onToggle: vi.fn(async () => true),
    onDelete: vi.fn(async () => true),
  }
  render(
    <ManagedList
      noun="category"
      placeholder="New category"
      entries={[{ id: 1, name: 'Glassware', active: true }, { id: 2, name: 'Old stock', active: false }]}
      {...handlers}
    />,
  )
  return { ...handlers, user: userEvent.setup() }
}

describe('ManagedList', () => {
  it('asks before deleting and leaves the value alone when cancelled', async () => {
    const { user, onDelete } = setup()
    await user.click(screen.getByRole('button', { name: 'Delete Glassware' }))
    expect(screen.getByRole('dialog', { name: 'Delete category' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('deletes the chosen value once confirmed', async () => {
    const { user, onDelete } = setup()
    await user.click(screen.getByRole('button', { name: 'Delete Old stock' }))
    await user.click(screen.getByRole('button', { name: 'Delete category' }))
    expect(onDelete).toHaveBeenCalledExactlyOnceWith(2)
  })

  it('switches a value off or on from its own row', async () => {
    const { user, onToggle } = setup()
    await user.click(screen.getByRole('button', { name: 'Make inactive Glassware' }))
    await user.click(screen.getByRole('button', { name: 'Make active Old stock' }))
    expect(onToggle.mock.calls).toEqual([[1, false], [2, true]])
    expect(screen.getByText('Inactive')).toBeTruthy()
  })

  it('renames in place and adds a new value from the top box', async () => {
    const { user, onRename, onAdd } = setup()
    await user.click(screen.getByRole('button', { name: 'Rename Glassware' }))
    const box = screen.getByRole('textbox', { name: 'Rename Glassware' })
    await user.clear(box)
    await user.type(box, 'Crockery{Enter}')
    expect(onRename).toHaveBeenCalledWith(1, 'Crockery')
    await user.type(screen.getByRole('textbox', { name: 'New category' }), 'Cutlery')
    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(onAdd).toHaveBeenCalledWith('Cutlery')
  })
})
