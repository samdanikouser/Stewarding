import { useState } from 'react'
import { PriceLine } from '@/components/charts'
import { Badge } from '@/components/ui/badge'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/table'
import { fmtDate } from '@/lib/format'
import { useMoney } from '@/lib/money'
import { qs, useApi } from '@/lib/useApi'

interface Point { date: string; price: number; qty: number; supplier: string | null; invoice: string; change_pct: number | null }
interface History {
  item: { code: string; name: string }
  points: Point[]
  summary: { count: number; first: number; latest: number; lowest: number; highest: number; average: number; change_pct: number | null } | null
}

const pct = (n: number | null | undefined) => (n == null ? '-' : `${n > 0 ? '+' : ''}${n}%`)

/** How the price paid for one item has moved from invoice to invoice. */
export function PriceTrend({ item, onClose }: { item: { id: number; code: string; name: string }; onClose: () => void }) {
  const money = useMoney()
  const [dateBy, setDateBy] = useState<'invoice' | 'received'>('invoice')
  const { data, error } = useApi<History>(`/inventory/items/${item.id}/price-history${qs({ date_by: dateBy })}`)
  const s = data?.summary

  return (
    <Modal open size="lg" title={`Price trend: ${item.name}`} description={`${item.code}. What each invoice paid per unit, after line discounts.`} onClose={onClose}>
      <div className="space-y-4">
        <Select aria-label="Date prices by" className="w-auto" value={dateBy} onChange={(e) => setDateBy(e.target.value as 'invoice' | 'received')}>
          <option value="invoice">By invoice date</option>
          <option value="received">By received date</option>
        </Select>
        {error ? <p role="alert" className="text-sm text-danger">{error}</p> : !data ? <Skeleton className="h-48 w-full" /> : !s ? (
          <p className="py-6 text-center text-sm text-ink-muted">No priced invoices for this item yet.</p>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
              {[['Latest', money(s.latest)], ['Lowest', money(s.lowest)], ['Highest', money(s.highest)], ['Average paid', money(s.average)]].map(([label, value]) => (
                <div key={label} className="rounded-lg bg-surface-muted px-3 py-2"><dt className="text-xs text-ink-muted">{label}</dt><dd className="font-semibold tabular-nums">{value}</dd></div>
              ))}
              <div className="rounded-lg bg-surface-muted px-3 py-2"><dt className="text-xs text-ink-muted">Since first invoice</dt>
                <dd><Badge tone={s.change_pct == null || s.change_pct === 0 ? 'neutral' : s.change_pct > 0 ? 'warn' : 'ok'}>{pct(s.change_pct)}</Badge></dd></div>
            </dl>
            <PriceLine format={money} points={data.points.map((p) => ({ label: fmtDate(p.date), value: p.price, sub: p.supplier ?? undefined }))} />
            <div className="max-h-64 overflow-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-muted text-left text-xs text-ink-muted"><tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Supplier</th><th className="px-3 py-2">Invoice</th><th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Price</th><th className="px-3 py-2 text-right">Change</th></tr></thead>
                <tbody className="divide-y divide-border">
                  {[...data.points].reverse().map((p) => (
                    <tr key={`${p.invoice}-${p.date}`}>
                      <td className="px-3 py-2">{fmtDate(p.date)}</td><td className="px-3 py-2">{p.supplier ?? '-'}</td><td className="px-3 py-2">{p.invoice}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{p.qty}</td><td className="px-3 py-2 text-right tabular-nums">{money(p.price)}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${p.change_pct != null && p.change_pct > 0 ? 'text-warn' : p.change_pct != null && p.change_pct < 0 ? 'text-ok' : 'text-ink-muted'}`}>{pct(p.change_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
