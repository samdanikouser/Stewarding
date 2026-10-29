import { AlertTriangle, ArrowLeftRight, Boxes, PackageMinus, TrendingDown, Wallet } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { ColumnChart } from '@/components/charts'
import { KpiCard } from '@/components/KpiCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/auth'
import { qs, useApi } from '@/lib/useApi'
import { useAllItems } from '@/lib/useItems'
import { useMoney } from '@/lib/money'

interface Props {
  locationId: number | null
}

interface Insights {
  movement: { date: string; in: number; out: number }[]
  totals: { in: number; out: number; breakage_units: number; breakage_cost: number }
  transfers: { requested: number }
}

interface Shortage {
  item_id: number
  code: string
  name: string
  location_id: number
  location: string
  qty: number
  minimum: number
  donors: { location_id: number; location: string; spare: number }[]
  suggested_qty: number
}

interface Txn { id: number; item_id: number; txn_type: string; qty_delta: number; occurred_at: string; user: string | null }

const SERIES = [
  { key: 'in', label: 'Stock in', className: 'bg-brand' },
  { key: 'out', label: 'Stock out', className: 'bg-warn' },
]

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

const DAYS = 14
const sinceDate = () => { const d = new Date(); d.setDate(d.getDate() - (DAYS - 1)); return d.toLocaleDateString('en-CA') }

const when = (iso: string) => new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export function InventoryOverview({ locationId }: Props) {
  const money = useMoney()
  const { byId } = useAllItems()
  const { me } = useAuth()
  const navigate = useNavigate()
  const canTransfer = me?.permissions.includes('stock.transfer') ?? false
  const insights = useApi<Insights>(`/stock/insights${qs({ location_id: locationId, date_from: sinceDate() })}`)
  const recent = useApi<{ items: Txn[] }>(`/inventory/transactions${qs({ location_id: locationId, size: 5 })}`)
  const all = useApi<{ total: number; total_value?: number }>(`/inventory/items${qs({ location_id: locationId, size: 1 })}`)
  const short = useApi<{ total: number; empty: number; items: Shortage[] }>(`/inventory/shortages${qs({ location_id: locationId })}`)
  const empty = short.data?.empty ?? 0
  const totals = insights.data?.totals

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard label="Total items" value={all.data?.total ?? '-'} icon={Boxes} />
        {all.data?.total_value !== undefined && <KpiCard label="Stock value" value={money(all.data.total_value)} icon={Wallet} />}
        <KpiCard label="Below minimum" value={short.data?.total ?? '-'} tone={short.data?.total ? 'warn' : 'ok'} icon={TrendingDown} />
        <KpiCard label="Out of stock" value={short.data ? empty : '-'} tone={empty ? 'critical' : 'ok'} icon={PackageMinus} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Inventory statistics</CardTitle>
          </CardHeader>
          <CardContent>
            {insights.data ? <ColumnChart data={insights.data.movement} labelKey="date" series={SERIES} /> : <div className="h-40 animate-pulse rounded-lg bg-surface-muted" />}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Alerts</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <AlertRow icon={AlertTriangle} tone="text-danger" text={`${plural(empty, 'place', 'places')} out of stock`} />
            <AlertRow icon={TrendingDown} tone="text-warn" text={`${plural(short.data?.total ?? 0, 'shortage', 'shortages')} below minimum`} />
            <AlertRow icon={ArrowLeftRight} tone="text-brand" text={`${plural(insights.data?.transfers.requested ?? 0, 'transfer', 'transfers')} requested`} to="/stock-movements" />
            <AlertRow icon={PackageMinus} tone="text-warn" text={`${plural(totals?.breakage_units ?? 0, 'unit', 'units')} broken or damaged`} to="/breakage" />
          </CardContent>
        </Card>
      </div>

      {!!short.data?.items.length && (
        <Card>
          <CardHeader><CardTitle>Shortages</CardTitle></CardHeader>
          <CardContent>
            <ul className="divide-y divide-border">
              {short.data.items.slice(0, 8).map((r) => {
                const donor = r.donors[0]
                return (
                  <li key={`${r.item_id}-${r.location_id}`} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                    <span>
                      <span className="font-medium">{r.name}</span> <span className="text-ink-muted">at {r.location}: {r.qty} of {r.minimum}</span>
                      {donor && <span className="block text-xs text-ink-muted">{donor.location} can spare {donor.spare}</span>}
                    </span>
                    {donor && canTransfer && (
                      <Button size="sm" variant="outline" onClick={() => navigate(`/stock-movements?tab=transfers&from=${donor.location_id}&to=${r.location_id}&item=${r.item_id}&qty=${r.suggested_qty}`)}>
                        Request transfer
                      </Button>
                    )}
                  </li>
                )
              })}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Recent activity</CardTitle></CardHeader>
        <CardContent>
          {recent.data?.items.length === 0 && <p className="text-sm text-ink-muted">No stock movements yet.</p>}
          <ul className="divide-y divide-border">
            {recent.data?.items.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span><span className="font-medium">{byId.get(t.item_id)?.name ??`Item ${t.item_id}`}</span> <span className="text-ink-muted">{t.txn_type.replace('_', ' ')}{t.user ? ` by ${t.user}` : ''}</span></span>
                <span className="flex items-center gap-3">
                  <span className={t.qty_delta > 0 ? 'font-medium text-ok' : 'font-medium text-danger'}>{t.qty_delta > 0 ? '+' : ''}{t.qty_delta}</span>
                  <span className="hidden text-xs text-ink-muted sm:inline">{when(t.occurred_at)}</span>
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}

function AlertRow({ icon: Icon, tone, text, to }: { icon: typeof AlertTriangle; tone: string; text: string; to?: string }) {
  const body = (
    <span className="flex items-center gap-2 rounded-lg bg-surface-muted px-3 py-2 text-sm">
      <Icon className={`h-4 w-4 shrink-0 ${tone}`} aria-hidden />{text}
    </span>
  )
  return to ? <Link to={to} className="block hover:opacity-80">{body}</Link> : body
}
