import { Boxes, PackageMinus, ShoppingCart, Wallet } from 'lucide-react'
import { useState } from 'react'
import { KpiCard } from '@/components/KpiCard'
import { Card, CardContent } from '@/components/ui/card'
import { LocationSelect } from '@/components/LocationSelect'
import { Input } from '@/components/ui/input'
import { EmptyState, Skeleton, Table, Td, Th } from '@/components/ui/table'
import { qs, useApi } from '@/lib/useApi'

interface Totals {
  opening_value: number
  purchases: number
  returns: number
  transfers_in: number
  transfers_out: number
  closing_value: number
  cost_consumed: number
  issued: number
  breakage_damage: number
  missing_written_off: number
  baseline_adjustments: number
  count_adjustments: number
}

interface CategoryLine extends Totals {
  category: string
  items: number
  share: number
}

interface ItemLine extends Totals {
  item_id: number
  code: string
  name: string
  category: string
  average_cost: number | null
}

interface Report {
  totals: Totals
  by_category: CategoryLine[]
  rows?: ItemLine[]
  locations?: { location_id: number; location: string; totals: Totals }[]
}

const money = (n: number | null | undefined) => (n ?? 0).toLocaleString('en-GB', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const thisMonth = () => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}` }

function period(month: string) {
  const [year, mon] = month.split('-').map(Number)
  const last = new Date(year, mon, 0).getDate()
  return { date_from: `${month}-01`, date_to: `${month}-${String(last).padStart(2, '0')}` }
}

export function CostTab() {
  const [locationId, setLocationId] = useState<number | null>(null)
  const [month, setMonth] = useState(thisMonth())
  const { data, loading, error } = useApi<Report>(`/stock/cost-report${qs({ ...period(month), location_id: locationId })}`)
  const t = data?.totals
  const year = month.slice(0, 4)
  const showYear = month.slice(5) !== '01'  // in January the month is the year so far
  const ytd = useApi<Report>(showYear ? `/stock/cost-report${qs({ date_from: `${year}-01-01`, date_to: period(month).date_to, location_id: locationId })}` : null).data

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <LocationSelect allowAll value={locationId} onChange={setLocationId} />
        <Input aria-label="Month" type="month" className="w-auto" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
      </div>

      {error && <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
      {loading && !data ? <Skeleton className="h-28 w-full" /> : t && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiCard icon={Wallet} label="Opening value" value={money(t.opening_value)} />
          <KpiCard icon={ShoppingCart} label="Purchases" value={money(t.purchases)} />
          <KpiCard icon={Boxes} label="Closing value" value={money(t.closing_value)} />
          <KpiCard icon={PackageMinus} label="Cost consumed" value={money(t.cost_consumed)} />
        </div>
      )}

      {t && (() => {
        const shortage = -t.count_adjustments  // a count that finds less than the books is use that was never written down
        const other = t.cost_consumed - t.issued - t.breakage_damage - t.missing_written_off - shortage
        const parts = [['Stock issued', t.issued], ['Breakage and damage', t.breakage_damage], ['Missing and written off', t.missing_written_off],
          [shortage >= 0 ? 'Count and round shortages' : 'Count and round surpluses', shortage], ['Other differences', Math.abs(other) < 0.0005 ? 0 : other]] as [string, number][]
        return (
          <Card>
            <CardContent className="space-y-2 py-4 text-sm">
              <p className="font-semibold">How Cost consumed is worked out</p>
              <p className="text-ink-muted">
                Opening {money(t.opening_value)} + purchases {money(t.purchases)} + returns to suppliers and other returns {money(t.returns)} + transfers in {money(t.transfers_in)}
                {t.baseline_adjustments !== 0 && ` + count-round baseline ${money(t.baseline_adjustments)}`}{' '}- transfers out {money(t.transfers_out)} - closing {money(t.closing_value)} = <span className="font-semibold text-ink">{money(t.cost_consumed)}</span>
              </p>
              <p className="text-ink-muted">
                It is made up of: {parts.map(([label, v]) => `${label} ${money(v)}`).join(', ')}.
                {parts[4][1] !== 0 && ' Other differences are usually a price difference between what was bought and the average cost, or stock entered without a price.'}
              </p>
              <p className="text-xs text-ink-muted">
                Purchases count on their invoice date and breakage on the day it was reported. The closing value is added up from every stock movement, while the Inventory page
                multiplies today's quantity by today's average cost, so the two can differ by a few cents from rounding.
              </p>
            </CardContent>
          </Card>
        )
      })()}

      {t && ytd && (
        <Card>
          <CardContent className="space-y-2 py-4">
            <p className="font-semibold">This month and the year so far</p>
            <Table>
              <thead><tr><Th>Measure</Th><Th className="text-right">{month}</Th><Th className="text-right">Year to date (1 Jan to month end)</Th></tr></thead>
              <tbody>
                {([['Opening value', 'opening_value'], ['Purchases', 'purchases'], ['Returns (net)', 'returns'], ['Transfers in', 'transfers_in'], ['Transfers out', 'transfers_out'],
                  ['Issued', 'issued'], ['Breakage and damage', 'breakage_damage'], ['Missing or written off', 'missing_written_off'], ['Round baseline', 'baseline_adjustments'],
                  ['Count gain (+) or loss (-)', 'count_adjustments'], ['Closing value', 'closing_value'], ['Cost consumed', 'cost_consumed']] as const).map(([label, key]) => (
                  <tr key={key} className={key === 'closing_value' || key === 'cost_consumed' ? 'font-semibold' : undefined}>
                    <Td>{label}</Td><Td className="text-right tabular-nums">{money(t[key])}</Td><Td className="text-right tabular-nums">{money(ytd.totals[key])}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p className="text-xs text-ink-muted">The year opens with {money(ytd.totals.opening_value)}. Each month's opening is the previous month's closing, so the opening changes from month to month while the year to date keeps adding up.</p>
          </CardContent>
        </Card>
      )}

      {data && data.by_category.length === 0 && <EmptyState title="No stock movement in this period" />}
      {data && data.by_category.length > 0 && (
        <>
          <h2 className="text-lg font-semibold">By category</h2>
          <Table>
            <thead><tr><Th>Category</Th><Th className="text-right">Items</Th><Th className="text-right">Opening</Th><Th className="text-right">Purchases</Th><Th className="text-right">Closing</Th><Th className="text-right">Cost consumed</Th>{ytd && <Th className="text-right">Consumed, year to date</Th>}<Th className="text-right">Share</Th></tr></thead>
            <tbody>
              {data.by_category.map((c) => (
                <tr key={c.category}>
                  <Td className="font-medium">{c.category}</Td>
                  <Td className="text-right tabular-nums">{c.items}</Td>
                  <Td className="text-right tabular-nums">{money(c.opening_value)}</Td>
                  <Td className="text-right tabular-nums">{money(c.purchases)}</Td>
                  <Td className="text-right tabular-nums">{money(c.closing_value)}</Td>
                  <Td className="text-right tabular-nums">{money(c.cost_consumed)}</Td>
                  {ytd && <Td className="text-right tabular-nums">{money(ytd.by_category.find((y) => y.category === c.category)?.cost_consumed)}</Td>}
                  <Td className="text-right tabular-nums">{c.share}%</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}

      {data?.locations && data.locations.length > 0 && (
        <>
          <h2 className="text-lg font-semibold">By location</h2>
          <Table>
            <thead><tr><Th>Location</Th><Th className="text-right">Opening</Th><Th className="text-right">Purchases</Th><Th className="text-right">Closing</Th><Th className="text-right">Cost consumed</Th></tr></thead>
            <tbody>
              {data.locations.map((l) => (
                <tr key={l.location_id}>
                  <Td className="font-medium">{l.location}</Td>
                  <Td className="text-right tabular-nums">{money(l.totals.opening_value)}</Td>
                  <Td className="text-right tabular-nums">{money(l.totals.purchases)}</Td>
                  <Td className="text-right tabular-nums">{money(l.totals.closing_value)}</Td>
                  <Td className="text-right tabular-nums">{money(l.totals.cost_consumed)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}

      {data?.rows && data.rows.length > 0 && (
        <>
          <h2 className="text-lg font-semibold">By item</h2>
          <Table>
            <thead><tr><Th>Item</Th><Th>Category</Th><Th className="text-right">Average cost</Th><Th className="text-right">Opening</Th><Th className="text-right">Purchases</Th><Th className="text-right">Closing</Th><Th className="text-right">Cost consumed</Th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.item_id}>
                  <Td className="font-medium">{r.code} - {r.name}</Td>
                  <Td>{r.category}</Td>
                  <Td className="text-right tabular-nums">{r.average_cost != null ? money(r.average_cost) : '-'}</Td>
                  <Td className="text-right tabular-nums">{money(r.opening_value)}</Td>
                  <Td className="text-right tabular-nums">{money(r.purchases)}</Td>
                  <Td className="text-right tabular-nums">{money(r.closing_value)}</Td>
                  <Td className="text-right tabular-nums">{money(r.cost_consumed)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}
    </div>
  )
}
