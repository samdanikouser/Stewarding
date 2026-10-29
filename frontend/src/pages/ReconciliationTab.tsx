import { useState } from 'react'
import { LocationSelect } from '@/components/LocationSelect'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { EmptyState, Table, Td, Th } from '@/components/ui/table'
import { useAuth } from '@/lib/auth'
import { qs, useApi } from '@/lib/useApi'
import { useMoney } from '@/lib/money'

interface Row {
  item_id: number
  code: string
  name: string
  opening: number
  opening_stock: number
  receipts: number
  returns: number
  issues: number
  breakage_damage: number
  transfers_in: number
  transfers_out: number
  adjustments: number
  closing: number
  counted_qty: number | null
  count_variance: number | null
  variance_value: number | null
  value: number | null
  closing_value: number
}

interface Variance {
  counted_items: number
  shortage_items: number
  surplus_items: number
  shortage_units: number
  surplus_units: number
  net_value: number
}

function Section({ rows, flaggedOnly }: { rows: Row[]; flaggedOnly: boolean }) {
  const money = useMoney()
  return (
    <>
    <Table>
      <thead>
        <tr>
          <Th>Item</Th><Th className="text-right">Opening</Th><Th className="text-right">Opening stock</Th><Th className="text-right">Receipts</Th>
          <Th className="text-right">Issues</Th><Th className="text-right">Breakage</Th><Th className="text-right">Transfers</Th>
          <Th className="text-right">Adjust.</Th><Th className="text-right">Closing</Th><Th className="text-right">Closing value</Th><Th className="text-right">Counted</Th><Th>Variance</Th>
        </tr>
      </thead>
      <tbody>
        {rows.filter((r) => !flaggedOnly || r.count_variance).map((r) => (
          <tr key={r.item_id} className={r.count_variance ? 'bg-warn-soft/40' : undefined}>
            <Td className="font-medium">{r.code} - {r.name}</Td>
            <Td className="text-right tabular-nums">{r.opening}</Td>
            <Td className="text-right tabular-nums">{r.opening_stock}</Td>
            <Td className="text-right tabular-nums">{r.receipts + r.returns}</Td>
            <Td className="text-right tabular-nums">{r.issues}</Td>
            <Td className="text-right tabular-nums">{r.breakage_damage}</Td>
            <Td className="text-right tabular-nums">{r.transfers_in + r.transfers_out}</Td>
            <Td className="text-right tabular-nums">{r.adjustments}</Td>
            <Td className="text-right font-medium tabular-nums">{r.closing}</Td>
            <Td className="text-right tabular-nums">{money(r.closing_value)}</Td>
            <Td className="text-right tabular-nums">{r.counted_qty ?? '-'}</Td>
            <Td>
              {r.count_variance ? <Badge tone={r.count_variance < 0 ? 'critical' : 'warn'}>{r.count_variance < 0 ? 'Short' : 'Over'} {Math.abs(r.count_variance)}{r.variance_value != null && ` (${money(r.variance_value)})`}</Badge>
                : r.counted_qty != null ? <Badge tone="ok">Matches</Badge> : <span className="text-ink-muted">Not counted</span>}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
      {rows.length === 0 && <EmptyState title="No stock activity for this month" />}
    </>
  )
}

export function ReconciliationTab() {
  const money = useMoney()
  const { me } = useAuth()
  const [locationId, setLocationId] = useState<number | null>(me?.locations[0]?.id ?? null)
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const { data } = useApi<{ rows: Row[]; total_closing: number; variance: Variance } | { locations: { location_id: number; location: string; rows: Row[]; total_closing: number; closing_value: number }[]; total_closing: number; closing_value: number; variance: Variance }>(
    month ? `/stock/reconciliation${qs({ location_id: locationId, month })}` : null,
  )

  return (
    <div className="space-y-4">
      <div className="filter-bar">
        <LocationSelect allowAll value={locationId} onChange={setLocationId} />
        <Input aria-label="Month" type="month" className="w-auto" value={month} onChange={(e) => setMonth(e.target.value)} />
      </div>
      {data && data.variance.counted_items > 0 && (
        <div role="status" className={`flex flex-wrap items-center gap-3 rounded-md border px-3 py-2 text-sm ${data.variance.shortage_items + data.variance.surplus_items ? 'border-warn/25 border-l-4 border-l-warn bg-warn-soft' : 'border-ok/25 border-l-4 border-l-ok bg-ok-soft'}`}>
          <span className="font-medium">{data.variance.counted_items} item(s) counted</span>
          {data.variance.shortage_items + data.variance.surplus_items === 0 ? <span>No variances: every count matched the system.</span> : (
            <>
              <Badge tone="critical">{data.variance.shortage_items} short ({data.variance.shortage_units} units)</Badge>
              <Badge tone="warn">{data.variance.surplus_items} over ({data.variance.surplus_units} units)</Badge>
              <span>Net value {money(data.variance.net_value)}</span>
            </>
          )}
          <label className="ml-auto flex items-center gap-2"><input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} /> Variances only</label>
        </div>
      )}
      {data && 'rows' in data && <Section rows={data.rows} flaggedOnly={flaggedOnly} />}
      {data && 'locations' in data && (
        <div className="space-y-6">
          {data.locations.map((l) => (
            <section key={l.location_id} aria-label={l.location} className="space-y-2">
              <h2 className="flex flex-wrap items-baseline gap-3 text-base font-semibold">{l.location}<span className="text-sm font-normal text-ink-muted">closing {l.total_closing} units, value {money(l.closing_value)}</span></h2>
              <Section rows={l.rows} flaggedOnly={flaggedOnly} />
            </section>
          ))}
          <p className="text-right text-sm">All locations: closing <span className="font-semibold tabular-nums">{data.total_closing}</span> units, value <span className="ml-1 text-base font-semibold tabular-nums">{money(data.closing_value)}</span></p>
        </div>
      )}
    </div>
  )
}
