import { Download } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { Skeleton, Table, Td, Th } from '@/components/ui/table'
import { Pagination } from '@/components/ui/pagination'
import { tokenStore } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { iso } from '@/lib/dates'
import { fmtDateTime } from '@/lib/format'
import { qs, useApi } from '@/lib/useApi'

interface Story {
  item: { id: number; code: string; name: string; unit: string | null }
  opening_balance: number
  closing: number
  received_net: number
  on_hand_now: number
  adds_up: boolean | null
  totals: { kind: string; label: string; qty: number }[]
  total: number
  rows: { id: number; at: string; location: string | null; kind: string; label: string; qty: number; balance: number; document: string | null; reason: string | null; by: string | null; unit_cost?: number | null }[]
}

const SIZE = 25

/** Everything that ever happened to one item: what came in, what was adjusted or used, and what is left, with a running balance. */
export function ItemHistory({ item, onClose }: { item: { id: number; code: string; name: string }; onClose: () => void }) {
  const { me } = useAuth()
  const [locationId, setLocationId] = useState<number | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const query = qs({ location_id: locationId, date_from: from, date_to: to })
  const { data, error } = useApi<Story>(`/inventory/items/${item.id}/history${query}${query ? '&' : '?'}page=${page}&size=${SIZE}`)
  const today = iso(new Date())
  const yearStart = `${today.slice(0, 4)}-01-01`
  const monthStart = `${today.slice(0, 7)}-01`
  const range = from === '' && to === '' ? 'all' : from === yearStart && to === '' ? 'year' : from === monthStart && to === '' ? 'month' : 'custom'
  const pick = (start: string) => { setFrom(start); setTo(''); setPage(1) }
  // the year so far is always shown beside whatever is selected, so it is one glance away
  const yearToDate = useApi<Story>(`/inventory/items/${item.id}/history${qs({ location_id: locationId, date_from: yearStart })}&page=1&size=1`).data

  async function download() {
    const blob = await fetch(`/api/inventory/items/${item.id}/history.csv${query}`, { headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}` } }).then((r) => r.blob()).catch(() => null)
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${item.code}-history.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  const unit = data?.item.unit ?? ''
  const sign = (n: number) => (n > 0 ? `+${n}` : String(n))
  const cards = data ? [
    ...data.totals.filter((t) => t.kind === 'opening').map((t) => ({ label: t.label, qty: t.qty, signed: false })),
    { label: 'Received (net of voids and returns)', qty: data.received_net, signed: false },
    ...data.totals.filter((t) => !['opening', 'received', 'invoice_void', 'supplier_return'].includes(t.kind)).map((t) => ({ label: t.label, qty: t.qty, signed: true })),
    { label: 'On hand now', qty: data.on_hand_now, signed: false },
  ] : []
  return (
    <Modal open size="xl" title={`History: ${item.name}`} description={`${item.code}. Every movement is kept, so received quantities and adjustments stay separate.`} onClose={onClose}>
      <div className="space-y-4">
        <div className="filter-bar">
          <Select aria-label="Location" className="w-auto" value={locationId ?? ''} onChange={(e) => { setLocationId(e.target.value ? Number(e.target.value) : null); setPage(1) }}>
            <option value="">All locations</option>
            {me?.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </Select>
          {([['all', 'All time', ''], ['year', 'This year', yearStart], ['month', 'This month', monthStart]] as const).map(([key, label, start]) => (
            <Button key={key} size="sm" variant={range === key ? 'default' : 'outline'} aria-pressed={range === key} onClick={() => pick(start)}>{label}</Button>
          ))}
          <Input aria-label="From date" type="date" className="w-auto" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1) }} />
          <Input aria-label="To date" type="date" className="w-auto" value={to} onChange={(e) => { setTo(e.target.value); setPage(1) }} />
          <Button variant="outline" size="sm" onClick={download}><Download className="h-4 w-4" /> Download</Button>
        </div>
        {error ? <p role="alert" className="text-sm text-danger">{error}</p> : !data ? <Skeleton className="h-64 w-full" /> : (
          <>
            <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              {cards.map((c) => (
                <div key={c.label} className="rounded-lg bg-surface-muted px-3 py-2">
                  <dt className="text-xs text-ink-muted">{c.label}</dt>
                  <dd className="font-semibold tabular-nums">{c.signed ? sign(c.qty) : c.qty} <span className="text-xs font-normal text-ink-muted">{unit}</span></dd>
                </div>
              ))}
            </dl>
            {yearToDate && (
              <p className="rounded-lg border border-border px-3 py-2 text-sm" aria-label="Year to date">
                <span className="font-medium">Year to date (since 1 Jan):</span>{' '}
                received {yearToDate.received_net}
                {yearToDate.totals.filter((t) => !['opening', 'received', 'invoice_void', 'supplier_return'].includes(t.kind)).map((t) => `, ${t.label.toLowerCase()} ${t.qty > 0 ? '+' : ''}${t.qty}`).join('')}
                . Opened the year with {yearToDate.opening_balance}, now {yearToDate.closing}.
              </p>
            )}
            <p className="text-sm text-ink-muted">
              {data.opening_balance !== 0 && <>Balance before this period {data.opening_balance}. </>}
              Movements add up to <span className="font-semibold text-ink">{data.closing}</span>.{' '}
              {data.adds_up === true && <Badge tone="ok">Matches what is on hand</Badge>}
              {data.adds_up === false && <Badge tone="critical">Does not match what is on hand: {data.on_hand_now}</Badge>}
            </p>
            <Table>
              <thead><tr><Th>When</Th><Th>What</Th><Th>Where</Th><Th className="text-right">Qty</Th><Th className="text-right">Balance</Th><Th>Document and reason</Th><Th>By</Th></tr></thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id}>
                    <Td className="whitespace-nowrap text-xs">{fmtDateTime(r.at)}</Td>
                    <Td>{r.label}</Td>
                    <Td>{r.location}</Td>
                    <Td className={`text-right tabular-nums ${r.qty < 0 ? 'text-danger' : 'text-ok'}`}>{sign(r.qty)}</Td>
                    <Td className="text-right tabular-nums">{r.balance}</Td>
                    <Td className="text-xs">{r.document && <span className="block font-medium">{r.document}</span>}<span className="text-ink-muted">{r.reason}</span></Td>
                    <Td className="text-xs">{r.by}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {data.rows.length === 0 && <p className="py-4 text-center text-sm text-ink-muted">No movements for this selection.</p>}
            <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </div>
    </Modal>
  )
}
