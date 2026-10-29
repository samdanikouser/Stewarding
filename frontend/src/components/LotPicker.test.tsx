import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LotPicker, type LotChoice } from '@/components/LotPicker'

const api = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ api }))
vi.mock('@/components/LotScanner', () => ({ LotScanner: () => null }))

const fresh = { id: 1, code: 'POU-260302-01', item: 'Chicken breast', use_by: '2026-03-10T20:00:00Z', past_use_by: false, condition_label: 'Chilled, raw', location: 'Main Kitchen', pack: null }
const old = { ...fresh, id: 2, code: 'POU-260301-01', past_use_by: true }

function Harness({ max }: { max?: number }) {
  const [value, setValue] = useState<LotChoice[]>([])
  return <LotPicker value={value} onChange={setValue} max={max} />
}

beforeEach(() => {
  api.mockReset()
  api.mockImplementation(async (path: string) => {
    if (path.startsWith('/lots/search')) return [fresh, old]
    if (path.includes('POU-260302-01')) return { id: 1, code: 'POU-260302-01', blocked: null }
    if (path.includes('HELD-1')) return { id: 9, code: 'HELD-1', blocked: 'HELD-1 is on hold' }
    throw new Error('No lot has that code')
  })
})

describe('LotPicker', () => {
  it('finds lots as you type and adds the one you choose as a chip you can remove', async () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Lot code or food name'), { target: { value: 'chicken' } })
    fireEvent.click(await screen.findByRole('button', { name: /POU-260302-01/ }))
    expect(screen.getByRole('list', { name: 'Chosen lots' })).toHaveTextContent('POU-260302-01')
    fireEvent.click(screen.getByLabelText('Remove POU-260302-01'))
    expect(screen.queryByRole('list', { name: 'Chosen lots' })).not.toBeInTheDocument()
  })

  it('shows the portion name and the supplier batch beside the lot code', async () => {
    api.mockImplementation(async () => [{ ...fresh, pack: '200 g breast portions', supplier_lot: 'B2610-884' }])
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Lot code or food name'), { target: { value: 'portions' } })
    expect(await screen.findByRole('button', { name: /200 g breast portions, supplier batch B2610-884/ })).toBeInTheDocument()
  })

  it('does not let a lot past its use-by date be picked from the list', async () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Lot code or food name'), { target: { value: 'chicken' } })
    expect(await screen.findByRole('button', { name: /POU-260301-01/ })).toBeDisabled()
    expect(screen.getByText('Past use-by')).toBeInTheDocument()
  })

  it('adds a typed code on Enter and refuses a lot that is on hold, saying why', async () => {
    render(<Harness />)
    const box = screen.getByLabelText('Lot code or food name')
    fireEvent.change(box, { target: { value: 'HELD-1' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(await screen.findByRole('alert')).toHaveTextContent('HELD-1 is on hold')
    expect(screen.queryByRole('list', { name: 'Chosen lots' })).not.toBeInTheDocument()
    fireEvent.change(box, { target: { value: 'NOPE' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No lot has that code'))
  })

  it('with a limit of one, hides the box once a lot is chosen', async () => {
    render(<Harness max={1} />)
    const box = screen.getByLabelText('Lot code or food name')
    fireEvent.change(box, { target: { value: 'POU-260302-01' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    await screen.findByRole('list', { name: 'Chosen lots' })
    expect(screen.queryByLabelText('Lot code or food name')).not.toBeInTheDocument()
  })

  it('keeps a typed name for food that has no lot, and clears it when a lot is chosen', async () => {
    function Typed() {
      const [lots, setLots] = useState<LotChoice[]>([])
      const [name, setName] = useState('')
      return <><LotPicker value={lots} onChange={setLots} allowCustom={{ value: name, onChange: setName }} /><output data-testid="name">{name}</output></>
    }
    render(<Typed />)
    const box = screen.getByLabelText('Lot code or food name')
    fireEvent.change(box, { target: { value: 'house sauce' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Use "house sauce" as typed' }))
    expect(screen.getByTestId('name').textContent).toBe('house sauce')
    expect(screen.getByRole('list', { name: 'Typed name' })).toHaveTextContent('house sauce')
    fireEvent.change(box, { target: { value: 'chicken' } })
    fireEvent.click(await screen.findByRole('button', { name: /POU-260302-01/ }))
    expect(screen.getByTestId('name').textContent).toBe('')
    expect(screen.getByRole('list', { name: 'Chosen lots' })).toHaveTextContent('Chicken breast (POU-260302-01)')
  })

  it('uses what was typed when Enter is pressed and no lot has that code', async () => {
    function Typed() {
      const [lots, setLots] = useState<LotChoice[]>([])
      const [name, setName] = useState('')
      return <><LotPicker value={lots} onChange={setLots} allowCustom={{ value: name, onChange: setName }} /><output data-testid="name">{name}</output></>
    }
    render(<Typed />)
    const box = screen.getByLabelText('Lot code or food name')
    fireEvent.change(box, { target: { value: 'Satay marinade' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    await waitFor(() => expect(screen.getByTestId('name').textContent).toBe('Satay marinade'))
  })
})

