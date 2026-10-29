import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { WorkLocationSelect } from '@/components/WorkLocationSelect'

const mocks = vi.hoisted(() => ({ rostered: [] as unknown[], loading: false }))
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ me: { permissions: ['attendance.self'], locations: [
    { id: 1, name: 'Main Kitchen' },
    { id: 2, name: 'Banquet Hall' },
  ] } }),
}))
vi.mock('@/lib/useApi', () => ({ useApi: () => ({ loading: mocks.loading, data: mocks.loading ? null : { rostered_today: mocks.rostered } }) }))

function Harness({ start = null, label }: { start?: number | null; label?: string }) {
  const [value, setValue] = useState<number | null>(start)
  return <><WorkLocationSelect value={value} onChange={setValue} label={label} fill={label !== undefined} /><output data-testid="chosen">{String(value)}</output></>
}

const at = (id: number, name: string) => ({ location_id: id, location_name: name, week_off: false })

describe('WorkLocationSelect', () => {
  it('fixes the location to the rostered one and opens the choice on request', async () => {
    mocks.loading = false
    mocks.rostered = [at(2, 'Banquet Hall')]
    render(<Harness />)
    expect(screen.getByText('Banquet Hall (rostered today)')).toBeTruthy()
    expect(screen.getByTestId('chosen').textContent).toBe('2')
    expect(screen.queryByLabelText('Location')).toBeNull()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Viewing another location?' }))
    expect((screen.getByLabelText('Location') as HTMLSelectElement).value).toBe('2')
  })

  it('stays open when not rostered, or when a different location was already chosen', () => {
    mocks.loading = false
    mocks.rostered = []
    const { unmount } = render(<Harness />)
    expect(screen.getByLabelText('Location')).toBeTruthy()
    unmount()
    mocks.rostered = [at(2, 'Banquet Hall')]
    render(<Harness start={1} />)
    expect((screen.getByLabelText('Location') as HTMLSelectElement).value).toBe('1')
  })

  it('keeps its label in a form, locked or open', async () => {
    mocks.loading = false
    mocks.rostered = [at(2, 'Banquet Hall')]
    render(<Harness label="Received at" />)
    expect(screen.getByText('Received at')).toBeTruthy()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Viewing another location?' }))
    expect(screen.getByLabelText('Received at')).toBeTruthy()
  })
})
