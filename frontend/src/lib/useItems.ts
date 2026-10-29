import { useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api'

export interface Item {
  id: number
  code: string
  name: string
  category_id: number
  unit_id: number
  category: string
  unit: string
  description: string | null
  image_path: string | null
  storage_location: string | null
  min_level: number
  target_level: number | null
  supplier_id: number | null
  supplier: string | null
  supplier_ids?: number[]
  other_suppliers?: string[]
  is_tracked_asset: boolean
  active: boolean
  qty: number
  received: number
  received_by_location: Record<string, number>
  by_location: Record<string, number>
  low: boolean
  short_at: { location_id: number; qty: number; minimum: number }[]
  location_minimums: Record<string, number>
  minimum: number
  unit_cost?: number | null
  avg_cost?: number | null
  last_purchase?: { price: number; date: string; supplier: string | null } | null
  value?: number | null
}

const PAGE = 200  // the most the server returns in one page

/** Every active item, for pickers and name lookups: pages are fetched until the last one, so none beyond the first 200 is missing. */
export function useAllItems(): { items: Item[]; byId: Map<number, Item> } {
  const [items, setItems] = useState<Item[]>([])

  useEffect(() => {
    let live = true
    ;(async () => {
      const found: Item[] = []
      for (let page = 1; ; page++) {
        const got = await api<{ total: number; items: Item[] }>(`/inventory/items?size=${PAGE}&page=${page}`)
        found.push(...got.items)
        if (!live || got.items.length < PAGE || found.length >= got.total) break
      }
      if (live) setItems(found)
    })().catch(() => undefined)
    return () => {
      live = false
    }
  }, [])

  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items])
  return { items, byId }
}
