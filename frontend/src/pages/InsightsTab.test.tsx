import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { InsightsTab } from '@/pages/InsightsTab'

const mocks = vi.hoisted(() => ({ paths: [] as (string | null)[] }))
vi.mock('@/lib/useApi', async (original) => ({
  ...(await original<typeof import('@/lib/useApi')>()),
  useApi: (path: string | null) => { mocks.paths.push(path); return { data: undefined, error: null, reload: vi.fn() } },
}))
vi.mock('@/components/LocationSelect', () => ({ LocationSelect: () => null }))

describe('InsightsTab custom period', () => {
  beforeEach(() => { mocks.paths = [] })

  it('lets a manager choose any dates and asks for exactly that period', () => {
    render(<InsightsTab />)
    fireEvent.click(screen.getByRole('button', { name: 'Custom period' }))
    fireEvent.change(screen.getByLabelText('From date'), { target: { value: '2026-01-05' } })
    fireEvent.change(screen.getByLabelText('To date'), { target: { value: '2026-02-20' } })
    const last = mocks.paths.filter((p) => p?.startsWith('/stock/insights')).at(-1)
    expect(last).toContain('date_from=2026-01-05')
    expect(last).toContain('date_to=2026-02-20')
  })

  it('waits when the start is after the end instead of asking the server', () => {
    render(<InsightsTab />)
    fireEvent.click(screen.getByRole('button', { name: 'Custom period' }))
    fireEvent.change(screen.getByLabelText('From date'), { target: { value: '2026-03-10' } })
    fireEvent.change(screen.getByLabelText('To date'), { target: { value: '2026-03-01' } })
    expect(mocks.paths.at(-1)).toBeNull()
    expect(screen.getByText(/start date that is not after/)).toBeTruthy()
  })
})
