import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsItems } from '@/pages/settings/SettingsItems'

const mocks = vi.hoisted(() => ({ paths: [] as string[] }))
const item = { id: 1, code: 'ITM-00001', name: 'Dinner plate', category: 'Crockery', unit: 'pcs', supplier: 'Plateworks', is_tracked_asset: false, active: true, min_level: 10, target_level: 40, unit_cost: 2.5, image_path: 'abc.jpg' }

vi.mock('@/lib/api', () => ({ api: vi.fn(async () => ({})) }))
vi.mock('@/lib/toast', () => ({ useRun: () => async () => true }))
vi.mock('@/pages/ItemForm', () => ({ ItemForm: () => null }))
vi.mock('@/components/ItemThumb', () => ({ ItemThumb: ({ path }: { path: string | null }) => <span data-testid="thumb">{path}</span> }))
vi.mock('@/lib/useApi', () => ({
  qs: (p: Record<string, unknown>) => `?${Object.entries(p).filter(([, v]) => v !== '').map(([k, v]) => `${k}=${v}`).join('&')}`,
  useApi: (path: string) => {
    mocks.paths.push(path)
    return { reload: () => undefined, data: path.startsWith('/inventory/items') ? { total: 1, items: [item] } : [] }
  },
}))

describe('SettingsItems views', () => {
  beforeEach(() => {
    localStorage.clear()
    mocks.paths.length = 0
  })

  it('shows cards by default with the thumbnail, then a grid of tiles and a list', async () => {
    const user = userEvent.setup()
    render(<SettingsItems />)
    expect(screen.getByText('Minimum / target')).toBeTruthy()
    expect(screen.getByTestId('thumb').textContent).toBe('abc.jpg')

    await user.click(screen.getByRole('button', { name: 'Grid' }))
    expect(screen.queryByText('Minimum / target')).toBeNull()
    expect(screen.getByRole('button', { name: 'Edit Dinner plate' })).toBeTruthy()
    expect(mocks.paths.some((p) => p.includes('size=24'))).toBe(true)

    await user.click(screen.getByRole('button', { name: 'List' }))
    expect(screen.getByText(/ITM-00001 - Crockery - pcs - Plateworks/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Actions for Dinner plate' })).toBeTruthy()
    expect(mocks.paths.some((p) => p.includes('size=25'))).toBe(true)
  })
})
