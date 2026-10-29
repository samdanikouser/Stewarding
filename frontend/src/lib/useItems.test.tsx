import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useAllItems } from '@/lib/useItems'

const mocks = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('@/lib/api', () => ({ api: mocks.api }))

describe('useAllItems', () => {
  it('keeps asking for pages until every item is loaded, so the 201st is not lost', async () => {
    const all = Array.from({ length: 230 }, (_, i) => ({ id: i + 1, code: `C${i + 1}`, name: `Item ${i + 1}` }))
    mocks.api.mockImplementation(async (path: string) => {
      const page = Number(/page=(\d+)/.exec(path)![1])
      return { total: 230, items: all.slice((page - 1) * 200, page * 200) }
    })
    const { result } = renderHook(() => useAllItems())
    await waitFor(() => expect(result.current.items).toHaveLength(230))
    expect(result.current.byId.get(201)?.name).toBe('Item 201')
    expect(mocks.api).toHaveBeenCalledTimes(2)
  })
})
