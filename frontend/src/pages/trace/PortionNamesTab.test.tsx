import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PortionNamesTab } from '@/pages/trace/PortionNamesTab'

const mocks = vi.hoisted(() => ({ api: vi.fn(async () => ({})), reload: vi.fn() }))
vi.mock('@/lib/api', () => ({ api: mocks.api }))
vi.mock('@/lib/toast', () => ({ useRun: () => async (action: () => Promise<unknown>) => (await action(), true) }))
vi.mock('@/lib/useApi', () => ({
  useApi: (path: string) => ({
    reload: mocks.reload,
    data: path.startsWith('/lots/portion-names')
      ? [{ id: 1, name: 'Breast portions', food_item_id: 4, food_item: 'Chicken breast', active: true }]
      : [{ id: 4, name: 'Chicken breast' }],
  }),
}))

describe('PortionNamesTab', () => {
  beforeEach(() => mocks.api.mockClear())

  it('lists the names with the food item they belong to', () => {
    render(<PortionNamesTab />)
    expect(screen.getByText('Breast portions')).toBeTruthy()
    expect(screen.getByText('Chicken breast')).toBeTruthy()
  })

  it('adds a name tied to a food item', async () => {
    const user = userEvent.setup()
    render(<PortionNamesTab />)
    await user.click(screen.getByRole('button', { name: /Add portion name/ }))
    await user.type(screen.getByLabelText('Portion name'), 'Satay skewers')
    await user.selectOptions(screen.getByLabelText('Food item (optional)'), '4')
    await user.click(screen.getByRole('button', { name: 'Save portion name' }))
    expect(mocks.api).toHaveBeenCalledWith('/lots/portion-names', { body: { name: 'Satay skewers', food_item_id: 4 } })
    expect(mocks.reload).toHaveBeenCalled()
  })
})
