import { History, Pencil, Plus, Power, Search, Trash2, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { ItemThumb } from '@/components/ItemThumb'
import { ActionMenu } from '@/components/ui/action-menu'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { CardGrid, RecordCard, SectionHeader } from '@/components/ui/record-card'
import { Select } from '@/components/ui/select'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { ViewSwitch } from '@/components/ui/view-switch'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import type { Item } from '@/lib/useItems'
import { useViewMode } from '@/lib/viewMode'
import { ItemForm } from '@/pages/ItemForm'
import { useMoney } from '@/lib/money'
import { PriceTrend } from '@/pages/PriceTrend'
import { ItemHistory } from '@/pages/ItemHistory'

const SIZES = { cards: 12, grid: 24, list: 25 }

export function SettingsItems() {
  const money = useMoney()
  const run = useRun()
  const [categoryId, setCategoryId] = useState('')
  const [search, setSearch] = useState('')
  const [active, setActive] = useState('true')
  const [page, setPage] = useState(1)
  const [view, chooseView] = useViewMode('items')
  const SIZE = SIZES[view]
  const [editing, setEditing] = useState<Item | null>(null)
  const [trend, setTrend] = useState<Item | null>(null)
  const [history, setHistory] = useState<Item | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [removing, setRemoving] = useState<Item | null>(null)
  const categories = useApi<{ id: number; name: string }[]>('/inventory/categories')
  const { data, reload } = useApi<{ total: number; items: Item[] }>(
    `/inventory/items${qs({ category_id: categoryId, search, active, page, size: SIZE })}`,
  )

  async function toggle(item: Item) {
    const ok = await run(() => api(`/inventory/items/${item.id}`, { method: 'PUT', body: { active: !item.active } }),
      item.active ? 'Item made inactive' : 'Item made active')
    if (ok) reload()
  }

  async function remove() {
    if (!removing) return
    const done = await run(() => api(`/inventory/items/${removing.id}`, { method: 'DELETE' }), 'Item deleted')
    setRemoving(null)
    if (done) reload()
  }

  const openEdit = (item: Item) => { setEditing(item); setFormOpen(true) }
  const actionsOf = (i: Item) => [
    { label: 'Edit', icon: Pencil, onClick: () => openEdit(i) },
    { label: 'History', icon: History, onClick: () => setHistory(i) },
    ...(i.avg_cost !== undefined ? [{ label: 'Price trend', icon: TrendingUp, onClick: () => setTrend(i) }] : []),
    { label: i.active ? 'Make inactive' : 'Make active', icon: Power, onClick: () => toggle(i) },
    { label: 'Delete', icon: Trash2, tone: 'danger' as const, onClick: () => setRemoving(i) },
  ]
  const statusBadges = (i: Item) => <>{i.is_tracked_asset && <Badge>Asset</Badge>}<Badge tone={i.active ? 'ok' : 'neutral'}>{i.active ? 'Active' : 'Inactive'}</Badge></>

  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(1) }

  return (
    <div className="space-y-6">
      <SectionHeader title="Item master" count={data?.total}
        action={<div className="flex flex-wrap items-center gap-3">
          <ViewSwitch value={view} onChange={(mode) => { chooseView(mode); setPage(1) }} />
          <Button onClick={() => { setEditing(null); setFormOpen(true) }}><Plus className="h-4 w-4" /> Add item</Button>
        </div>} />

      <div className="flex flex-wrap gap-3 rounded-xl border border-border bg-surface p-4">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink-muted" aria-hidden />
          <Input aria-label="Search items" className="pl-9" placeholder="Search name or code" value={search} onChange={(e) => reset(setSearch)(e.target.value)} />
        </div>
        <Select aria-label="Category" className="w-auto" value={categoryId} onChange={(e) => reset(setCategoryId)(e.target.value)}>
          <option value="">All categories</option>
          {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
        <Select aria-label="Status" className="w-auto" value={active} onChange={(e) => reset(setActive)(e.target.value)}>
          <option value="true">Active items</option>
          <option value="false">Inactive items</option>
        </Select>
      </div>

      {!data ? <Skeleton className="h-48 w-full" /> : data.items.length === 0 ? <EmptyState title="No items found" /> : view === 'cards' ? (
        <CardGrid>
          {data.items.map((i) => (
            <RecordCard
              key={i.id}
              title={i.name}
              subtitle={`${i.code} - ${i.category}`}
              inactive={!i.active}
              media={<ItemThumb path={i.image_path} name={i.name} className="h-14 w-14" />}
              badges={statusBadges(i)}
              facts={[
                { label: 'Unit', value: i.unit },
                { label: 'Preferred supplier', value: i.supplier ?? '-' },
                ...(i.other_suppliers?.length ? [{ label: 'Also bought from', value: i.other_suppliers.join(', ') }] : []),
                { label: 'Starting price', value: i.unit_cost != null ? money(i.unit_cost) : '-' },
                { label: 'Average cost', value: i.avg_cost != null ? money(i.avg_cost) : '-' },
                { label: 'Last purchase', value: i.last_purchase ? `${money(i.last_purchase.price)} on ${fmtDate(i.last_purchase.date)}${i.last_purchase.supplier ? `, ${i.last_purchase.supplier}` : ''}` : '-' },
                { label: 'Minimum / target', value: `${i.min_level} / ${i.target_level ?? '-'}` },
              ]}
              actions={actionsOf(i)}
            />
          ))}
        </CardGrid>
      ) : view === 'grid' ? (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {data.items.map((i) => (
            <li key={i.id}>
              <Card className={`flex h-full flex-col overflow-hidden transition-shadow hover:shadow-md ${i.active ? '' : 'bg-surface-muted/60'}`}>
                <button type="button" aria-label={`Edit ${i.name}`} onClick={() => openEdit(i)} className="block text-left">
                  <ItemThumb path={i.image_path} name={i.name} className="aspect-square w-full rounded-none" />
                </button>
                <div className="flex flex-1 items-start justify-between gap-1 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{i.name}</p>
                    <p className="truncate text-xs text-ink-muted">{i.code} - {i.category}</p>
                    <div className="mt-2 flex flex-wrap gap-1">{statusBadges(i)}</div>
                  </div>
                  <ActionMenu label={`Actions for ${i.name}`} actions={actionsOf(i)} />
                </div>
              </Card>
            </li>
          ))}
        </ul>
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
          {data.items.map((i) => (
            <li key={i.id} className={`flex items-center gap-3 px-4 py-3 ${i.active ? '' : 'bg-surface-muted/60'}`}>
              <ItemThumb path={i.image_path} name={i.name} className="h-12 w-12" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{i.name}</p>
                <p className="truncate text-sm text-ink-muted">{i.code} - {i.category} - {i.unit}{i.supplier ? ` - ${i.supplier}` : ''}</p>
                {i.avg_cost !== undefined && (
                  <p className="truncate text-sm text-ink-muted">
                    Start {i.unit_cost != null ? money(i.unit_cost) : '-'} - Average {i.avg_cost != null ? money(i.avg_cost) : '-'} - Last bought {i.last_purchase ? `${money(i.last_purchase.price)} (${fmtDate(i.last_purchase.date)})` : '-'}
                  </p>
                )}
              </div>
              <div className="hidden shrink-0 gap-1.5 sm:flex">{statusBadges(i)}</div>
              <ActionMenu label={`Actions for ${i.name}`} actions={actionsOf(i)} />
            </li>
          ))}
        </ul>
      )}
      {data && <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />}

      {trend && <PriceTrend item={trend} onClose={() => setTrend(null)} />}
      {history && <ItemHistory item={history} onClose={() => setHistory(null)} />}
      {formOpen && <ItemForm item={editing} open onClose={() => setFormOpen(false)} onSaved={() => { setFormOpen(false); reload() }} />}

      <ConfirmDialog open={removing !== null} title="Delete item" confirmLabel="Delete item"
        message={`Delete ${removing?.name ?? 'this item'}? This cannot be undone. An item with stock, receipts, counts or other history cannot be deleted; make it inactive instead.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
