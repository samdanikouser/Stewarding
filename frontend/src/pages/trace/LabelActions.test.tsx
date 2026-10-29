import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LabelActions } from '@/pages/trace/LabelActions'

const mocks = vi.hoisted(() => ({ openPdf: vi.fn(async () => true), api: vi.fn(async () => ({})) }))
vi.mock('@/lib/download', () => ({ openPdf: mocks.openPdf, downloadFile: vi.fn(), fetchText: vi.fn() }))
vi.mock('@/lib/api', () => ({ api: mocks.api }))
vi.mock('@/lib/zebraLocal', () => ({ findLocalZebra: async () => null, printOnLocalZebra: vi.fn() }))
vi.mock('@/lib/toast', () => ({ useRun: () => async (action: () => Promise<unknown>) => (await action(), true), useToast: () => () => undefined }))
vi.mock('@/lib/useApi', () => ({ useApi: (path: string) => ({ data: path === '/label-printers' ? [{ id: 4, name: 'Pass printer', dpi: 203 }] : null }) }))

describe('LabelActions', () => {
  beforeEach(() => {
    mocks.openPdf.mockClear()
    mocks.api.mockClear()
  })

  it('offers one label for the container or a label for each pack, and sends the choice', async () => {
    const user = userEvent.setup()
    render(<LabelActions ids={[7]} packs={13} />)
    await user.click(screen.getByRole('button', { name: 'Labels as PDF' }))
    expect(mocks.openPdf).toHaveBeenLastCalledWith('/api/lots/labels?ids=7&copies=1&style=container')

    await user.click(screen.getByRole('button', { name: 'A label for each pack (13)' }))
    expect(screen.getByText(/13 labels will print/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Labels as PDF' }))
    expect(mocks.openPdf).toHaveBeenLastCalledWith('/api/lots/labels?ids=7&copies=1&style=pack')
    await user.click(screen.getByRole('button', { name: /Print to Pass printer/ }))
    expect(mocks.api).toHaveBeenCalledWith('/label-printers/print', { body: { printer_id: 4, lot_ids: [7], copies: 1, style: 'pack' } })
  })

  it('shows no choice for a lot that has no packs', () => {
    render(<LabelActions ids={[7]} />)
    expect(screen.queryByRole('group', { name: 'Label type' })).toBeNull()
  })
})
