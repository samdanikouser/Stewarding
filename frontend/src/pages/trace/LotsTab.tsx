import { Search } from 'lucide-react'
import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { FOOD_GROUPS } from '@/lib/reportCatalog'
import { qs, useApi } from '@/lib/useApi'
import { LotDetailModal } from '@/pages/trace/LotDetailModal'
import { LotFamily } from '@/pages/trace/LotFamily'
import { STATUS_LABEL, type Lot } from '@/pages/trace/types'

const SIZE = 15

export function LotsTab() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [group, setGroup] = useState('')
  const [supplier, setSupplier] = useState('')
  const [soon, setSoon] = useState(false)
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<number | null>(null)
  const suppliers = useApi<{ id: number; name: string }[]>('/lots/suppliers')
  const { data, loading, reload } = useApi<{ total: number; items: Lot[] }>(`/lots${qs({ grouped: true, q: search, status, food_group: group, supplier_id: supplier, expiring_hours: soon ? 48 : '', page, size: SIZE })}`)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface p-4">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink-muted" aria-hidden />
          <Input aria-label="Search lots" className="pl-9" placeholder="Lot code, food, portion name or supplier lot" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        </div>
        <Select aria-label="Status" className="w-auto" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="">Any status</option>
          {Object.entries(STATUS_LABEL).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
        </Select>
        <Select aria-label="Food group" className="w-auto" value={group} onChange={(e) => { setGroup(e.target.value); setPage(1) }}>
          <option value="">Any food group</option>
          {FOOD_GROUPS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </Select>
        {(suppliers.data?.length ?? 0) > 0 && (
          <Select aria-label="Supplier" className="w-auto" value={supplier} onChange={(e) => { setSupplier(e.target.value); setPage(1) }}>
            <option value="">Any supplier</option>
            {suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={soon} onChange={(e) => { setSoon(e.target.checked); setPage(1) }} /> Use-by within 48 hours
        </label>
      </div>
      {loading && !data && <Skeleton className="h-32 w-full" />}
      <div className="space-y-4">
        {data?.items.map((l) => <LotFamily key={l.id} lot={l} onOpen={setOpen} />)}
      </div>
      {data?.items.length === 0 && <EmptyState title="No lots found" />}
      {data && <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />}
      {open !== null && <LotDetailModal key={open} initialId={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </div>
  )
}
