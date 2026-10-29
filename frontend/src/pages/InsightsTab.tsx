import { useState } from 'react'
import { ColumnChart, QuantityBars } from '@/components/charts'
import { KpiCard } from '@/components/KpiCard'
import { LocationSelect } from '@/components/LocationSelect'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/table'
import { PRESETS, type Range } from '@/lib/dates'
import { qs, useApi } from '@/lib/useApi'
import { useMoney } from '@/lib/money'

interface Analysis {
  spend_trend: { period: string; spend: number }[]
  spend_by_supplier: { label: string; value: number }[]
  spend_by_category: { label: string; value: number }[]
  most_used_items: { label: string; value: number }[]
  stock_value_by_category: { label: string; value: number }[]
  total_spend: number
}

interface Insights {
  range: { grain: 'day' | 'month' }
  movement: { date: string; in: number; out: number }[]
  movement_by_type: { label: string; value: number }[]
  breakage_trend: { period: string; incidents: number; qty: number; est_cost: number }[]
  breakage_by_reason: { label: string; value: number }[]
  breakage_top_items: { label: string; value: number }[]
  transfers: { requested: number; completed: number; rejected: number; units: number }
  transfer_routes: { label: string; value: number; sub: string }[]
  totals: { in: number; out: number; breakage_units: number; breakage_cost: number }
}

export function InsightsTab() {
  const money = useMoney()
  const [preset, setPreset] = useState('last30')
  const [locationId, setLocationId] = useState<number | null>(null)
  const [custom, setCustom] = useState<Range>(() => (PRESETS[0].range() as Range))
  const range = (preset === 'custom' ? custom : (PRESETS.find((p) => p.key === preset) ?? PRESETS[0]).range()) as Range
  const rangeOk = range[0] !== '' && range[1] !== '' && range[0] <= range[1]
  const [dateBy, setDateBy] = useState<'invoice' | 'received'>('invoice')
  const query = qs({ location_id: locationId, date_from: range[0], date_to: range[1], date_by: dateBy })
  const { data, error } = useApi<Insights>(rangeOk ? `/stock/insights${query}` : null)
  const analysis = useApi<Analysis>(rangeOk ? `/stock/analysis${query}` : null).data
  const withMoney = (rows: { label: string; value: number }[]) => rows.map((r) => ({ ...r, sub: money(r.value) }))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {PRESETS.filter((p) => ['today', 'week', 'month', 'lastmonth', 'last30'].includes(p.key)).map((p) => (
          <Button key={p.key} size="sm" variant={preset === p.key ? 'default' : 'outline'} onClick={() => setPreset(p.key)}>{p.label}</Button>
        ))}
        <Button size="sm" variant={preset === 'custom' ? 'default' : 'outline'} onClick={() => setPreset('custom')}>Custom period</Button>
        {preset === 'custom' && (
          <>
            <Input aria-label="From date" type="date" className="w-auto" value={custom[0]} max={custom[1] || undefined} onChange={(e) => setCustom([e.target.value, custom[1]])} />
            <Input aria-label="To date" type="date" className="w-auto" value={custom[1]} min={custom[0] || undefined} onChange={(e) => setCustom([custom[0], e.target.value])} />
          </>
        )}
        <LocationSelect allowAll value={locationId} onChange={setLocationId} />
        <Select aria-label="Date deliveries by" className="w-auto" value={dateBy} onChange={(e) => setDateBy(e.target.value as 'invoice' | 'received')}>
          <option value="invoice">Deliveries by invoice date</option>
          <option value="received">Deliveries by received date</option>
        </Select>
      </div>
      {preset === 'custom' && !rangeOk && <p className="text-sm text-ink-muted">Choose a start date that is not after the end date.</p>}
      {error && <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
      {!data ? <Skeleton className="h-64 w-full" /> : (
        <>
          <section aria-label="Key figures" className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <KpiCard label="Stock in" value={data.totals.in} tone="ok" />
            <KpiCard label="Stock out" value={data.totals.out} />
            <KpiCard label="Breakage units" value={data.totals.breakage_units} tone={data.totals.breakage_units ? 'warn' : 'default'} />
            <KpiCard label="Transfers completed" value={data.transfers.completed} />
            <KpiCard label="Transfers waiting" value={data.transfers.requested} tone={data.transfers.requested ? 'warn' : 'default'} />
          </section>
          <section aria-label="Charts" className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Stock in and out {data.range.grain === 'month' ? 'by month' : 'by day'} ({dateBy === 'invoice' ? 'invoice date' : 'received date'})</CardTitle></CardHeader>
              <CardContent><ColumnChart data={data.movement} labelKey="date" series={[{ key: 'in', label: 'In', className: 'bg-ok' }, { key: 'out', label: 'Out', className: 'bg-brand' }]} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Breakage trend</CardTitle></CardHeader>
              <CardContent><ColumnChart data={data.breakage_trend} labelKey="period" series={[{ key: 'qty', label: 'Units broken', className: 'bg-danger' }, { key: 'incidents', label: 'Incidents', className: 'bg-warn' }]} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Movement by type (units)</CardTitle></CardHeader>
              <CardContent><QuantityBars items={data.movement_by_type} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Transfers between locations (units)</CardTitle></CardHeader>
              <CardContent><QuantityBars items={data.transfer_routes} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Breakage by reason (units)</CardTitle></CardHeader>
              <CardContent><QuantityBars items={data.breakage_by_reason} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Most broken items (units)</CardTitle></CardHeader>
              <CardContent><QuantityBars items={data.breakage_top_items} /></CardContent>
            </Card>
          </section>
          {analysis && (
            <section aria-label="Purchasing and stock value" className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader><CardTitle>Purchases (value) {data.range.grain === 'month' ? 'by month' : 'by day'}: {money(analysis.total_spend)}</CardTitle></CardHeader>
                <CardContent><ColumnChart data={analysis.spend_trend} labelKey="period" series={[{ key: 'spend', label: 'Purchases', className: 'bg-brand' }]} /></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Spend by supplier</CardTitle></CardHeader>
                <CardContent><QuantityBars items={withMoney(analysis.spend_by_supplier)} /></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Spend by category</CardTitle></CardHeader>
                <CardContent><QuantityBars items={withMoney(analysis.spend_by_category)} /></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Most used items (units issued)</CardTitle></CardHeader>
                <CardContent><QuantityBars items={analysis.most_used_items} /></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Stock value held now, by category</CardTitle></CardHeader>
                <CardContent><QuantityBars items={withMoney(analysis.stock_value_by_category)} /></CardContent>
              </Card>
            </section>
          )}
        </>
      )}
    </div>
  )
}
