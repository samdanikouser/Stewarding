import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { LocationSelect } from '@/components/LocationSelect'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { EmptyState, SkeletonRows, Table, Td, Th } from '@/components/ui/table'
import { fmtDate, fmtDateTime, label } from '@/lib/format'
import { qs, useApi } from '@/lib/useApi'
import { useAllItems } from '@/lib/useItems'
import { CostTab } from '@/pages/CostTab'
import { RoundsTab } from '@/pages/RoundsTab'
import { InsightsTab } from '@/pages/InsightsTab'
import { ReceivingTab } from '@/pages/ReceivingTab'
import { ReconciliationTab } from '@/pages/ReconciliationTab'
import { TransfersTab } from '@/pages/TransfersTab'

interface Txn {
  id: number
  item_id: number
  location_id: number
  txn_type: string
  qty_delta: number
  occurred_at: string
  invoice_date: string | null
  reason: string | null
  user: string | null
}

const TABS = [['insights', 'Insights'], ['transactions', 'Transactions'], ['receiving', 'Receiving'], ['transfers', 'Transfers'], ['rounds', 'Count rounds'], ['reconciliation', 'Reconciliation'], ['costs', 'Costs']] as const
const SIZE = 15

function Transactions() {
  const [locationId, setLocationId] = useState<number | null>(null)
  const [type, setType] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const { byId } = useAllItems()
  const { data, loading } = useApi<{ total: number; items: Txn[] }>(
    `/inventory/transactions${qs({ location_id: locationId, txn_type: type, date_from: from, date_to: to, page, size: SIZE })}`,
  )
  const places = new Map(useApi<{ id: number; name: string }[]>('/stock/locations').data?.map((l) => [l.id, l.name]))

  return (
    <div className="space-y-3">
      <div className="filter-bar">
        <LocationSelect allowAll value={locationId} onChange={(id) => { setLocationId(id); setPage(1) }} />
        <Select aria-label="Type" className="w-auto" value={type} onChange={(e) => { setType(e.target.value); setPage(1) }}>
          <option value="">All types</option>
          {['opening', 'receipt', 'issue', 'return', 'damage', 'breakage', 'transfer_in', 'transfer_out', 'adjustment'].map((t) => <option key={t} value={t}>{label(t)}</option>)}
        </Select>
        <Input aria-label="From date" type="date" className="w-auto" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1) }} />
        <Input aria-label="To date" type="date" className="w-auto" value={to} onChange={(e) => { setTo(e.target.value); setPage(1) }} />
      </div>
      <Table>
        <thead><tr><Th>Time</Th><Th>Invoice date</Th><Th>Item</Th><Th>Location</Th><Th>Type</Th><Th className="text-right">Qty</Th><Th>By</Th><Th>Reason</Th></tr></thead>
        <tbody>
          {loading && !data ? <SkeletonRows cols={8} /> : data?.items.map((t) => (
            <tr key={t.id}>
              <Td>{fmtDateTime(t.occurred_at)}</Td>
              <Td>{t.invoice_date ? fmtDate(t.invoice_date) : '-'}</Td>
              <Td className="font-medium">{byId.get(t.item_id)?.name ?? t.item_id}</Td>
              <Td>{places.get(t.location_id)}</Td>
              <Td>{label(t.txn_type)}</Td>
              <Td className={`text-right tabular-nums ${t.qty_delta < 0 ? 'text-danger' : 'text-ok'}`}>{t.qty_delta > 0 ? `+${t.qty_delta}` : t.qty_delta}</Td>
              <Td>{t.user}</Td>
              <Td className="text-ink-muted">{t.reason}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {data?.items.length === 0 && <EmptyState title="No stock movements for this selection" />}
      {data && <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />}
    </div>
  )
}

export function StockMovementsPage() {
  const [params] = useSearchParams()
  const wanted = params.get('tab') === 'counts' ? 'rounds' : params.get('tab')  // the old Physical counts address now opens count rounds
  const asked = TABS.find(([key]) => key === wanted)
  const [tab, setTab] = useState<(typeof TABS)[number][0]>(asked ? asked[0] : 'insights')
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Stock Movements &amp; Transfers</h1>
      <div role="tablist" className="flex flex-wrap gap-2">
        {TABS.map(([key, text]) => (
          <Button key={key} role="tab" aria-selected={tab === key} size="sm" variant={tab === key ? 'default' : 'outline'} onClick={() => setTab(key)}>{text}</Button>
        ))}
      </div>
      {tab === 'insights' && <InsightsTab />}
      {tab === 'transactions' && <Transactions />}
      {tab === 'receiving' && <ReceivingTab />}
      {tab === 'transfers' && <TransfersTab />}
      {tab === 'rounds' && <RoundsTab />}
      {tab === 'reconciliation' && <ReconciliationTab />}
      {tab === 'costs' && <CostTab />}
    </div>
  )
}
