import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ItemPicker } from '@/components/ItemPicker'
import type { Item } from '@/lib/useItems'

const make = (n: number) => ({ id: n, code: `IT-${String(n).padStart(3, '0')}`, name: n === 201 ? 'Saffron threads' : `Plain item ${n}` }) as Item
const items = Array.from({ length: 250 }, (_, i) => make(i + 1))

function Harness({ onPick }: { onPick: (id: string) => void }) {
  const [value, setValue] = useState('')
  return <ItemPicker items={items} value={value} onChange={(id) => { setValue(id); onPick(id) }} />
}

describe('ItemPicker', () => {
  it('finds an item past the 200th by typing part of its name', async () => {
    const onPick = vi.fn()
    render(<Harness onPick={onPick} />)
    const user = userEvent.setup()
    await user.type(screen.getByRole('combobox', { name: 'Item' }), 'saff')
    expect(screen.getAllByRole('option')).toHaveLength(1)
    await user.click(screen.getByRole('option', { name: /Saffron threads/ }))
    expect(onPick).toHaveBeenCalledWith('201')
    expect((screen.getByRole('combobox', { name: 'Item' }) as HTMLInputElement).value).toBe('IT-201 - Saffron threads')
  })

  it('also matches the code, picks with the keyboard, and says when nothing matches', async () => {
    const onPick = vi.fn()
    render(<Harness onPick={onPick} />)
    const user = userEvent.setup()
    const box = screen.getByRole('combobox', { name: 'Item' })
    await user.type(box, 'it-007{ArrowDown}{ArrowUp}{Enter}')
    expect(onPick).toHaveBeenCalledWith('7')
    await user.clear(box)
    await user.type(box, 'zzzz')
    expect(screen.getByText('No item matches')).toBeTruthy()
  })
})
