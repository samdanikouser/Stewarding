import { Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { LocationSelect } from '@/components/LocationSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Pagination } from '@/components/ui/pagination'
import { EmptyState, SkeletonRows, Table, Td, Th } from '@/components/ui/table'
import { useAuth } from '@/lib/auth'
import { qs, useApi } from '@/lib/useApi'
import type { Item } from '@/lib/useItems'
import { AssetsPanel } from '@/pages/AssetsPanel'
import { InventoryOverview } from '@/pages/InventoryOverview'
import { ItemForm } from '@/pages/ItemForm'
import { MinimumCell } from '@/pages/MinimumCell'
import { StockPostModal } from '@/pages/StockPostModal'
import { useMoney } from '@/lib/money'
import { PriceTrend } from '@/pages/PriceTrend'
import { ItemHistory } from '@/pages/ItemHistory'

interface Listing {
  total: number
  total_value?: number
  items: Item[]
}

const SIZE = 15

export function InventoryPage() {
  const money = useMoney()
  const { me } = useAuth()
  const can = (p: string) => me?.permissions.includes(p) ?? false
  const [locationId, setLocationId] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const [page, setPage] = useState(1)
  const [formItem, setFormItem] = useState<Item | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [posting, setPosting] = useState<Item | null>(null)
  const [trend, setTrend] = useState<Item | null>(null)
  const [history, setHistory] = useState<Item | null>(null)
  const [version, setVersion] = useState(0)
  const categories = useApi<{ id: number; name: string }[]>('/inventory/categories')

  const { data, loading, reload } = useApi<Listing>(
    `/inventory/items${qs({ search, category_id: categoryId, location_id: locationId, low_only: lowOnly, page, size: SIZE })}`,
  )
  const showCost = data?.items.some((i) => i.unit_cost !== undefined)
  const refresh = () => { reload(); setVersion((v) => v + 1) }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Inventory</h1>
        {can('inventory.manage') && <Button onClick={() => { setFormItem(null); setFormOpen(true) }}><Plus className="h-4 w-4" /> Add item</Button>}
      </div>

      <InventoryOverview key={version} locationId={locationId} />

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink-muted" aria-hidden />
          <Input aria-label="Search items" className="pl-9" placeholder="Search name or code" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        </div>
        <Select aria-label="Category" className="w-auto" value={categoryId} onChange={(e) => { setCategoryId(e.target.value); setPage(1) }}>
          <option value="">All categories</option>
          {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
        <LocationSelect allowAll value={locationId} onChange={(id) => { setLocationId(id); setPage(1) }} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={lowOnly} onChange={(e) => { setLowOnly(e.target.checked); setPage(1) }} /> Low stock only
        </label>
        {data?.total_value !== undefined && <Badge>Stock value {money(data.total_value)}</Badge>}
      </div>

      <Table>
        <thead>
          <tr><Th>Code</Th><Th>Item</Th><Th>Category</Th><Th>Unit</Th><Th className="text-right">In stock</Th><Th className="text-right">Minimum</Th>{showCost && <Th className="text-right">Value</Th>}<Th>Status</Th><Th /></tr>
        </thead>
        <tbody>
          {loading && !data ? <SkeletonRows cols={showCost ? 9 : 8} /> : data?.items.map((i) => (
            <tr key={i.id}>
              <Td>{i.code}</Td>
              <Td className="font-medium">{i.name}</Td>
              <Td>{i.category}</Td>
              <Td>{i.unit}</Td>
              <Td className="text-right tabular-nums">{i.qty}</Td>
              <Td><MinimumCell item={i} locationId={locationId} canEdit={can('inventory.count')} onSaved={refresh} /></Td>
              {showCost && <Td className="text-right tabular-nums">{i.value != null ? money(i.value) : '-'}</Td>}
              <Td>{i.low ? <Badge tone="critical">Low stock</Badge> : <Badge tone="ok">OK</Badge>}</Td>
              <Td>
                <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                <Button size="sm" variant="outline" onClick={() => setHistory(i)}>History</Button>
                {showCost && <Button size="sm" variant="outline" onClick={() => setTrend(i)}>Price trend</Button>}
                {can('stock.transfer') && <Button size="sm" variant="outline" onClick={() => setPosting(i)}>Stock</Button>}
                {can('inventory.manage') && <Button size="sm" variant="outline" onClick={() => { setFormItem(i); setFormOpen(true) }}>Edit</Button>}
                </div>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {data?.items.length === 0 && <EmptyState title="No items found" />}
      {data && <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />}

      <h2 className="pt-2 text-lg font-semibold">Tracked assets</h2>
      <AssetsPanel locationId={locationId} items={data?.items ?? []} />

      {formOpen && <ItemForm item={formItem} open onClose={() => setFormOpen(false)} onSaved={() => { setFormOpen(false); refresh() }} />}
      {trend && <PriceTrend item={trend} onClose={() => setTrend(null)} />}
      {history && <ItemHistory item={history} onClose={() => setHistory(null)} />}
      <StockPostModal item={posting} defaultLocation={locationId} onClose={() => setPosting(null)} onPosted={() => { setPosting(null); refresh() }} />
    </div>
  )
}
