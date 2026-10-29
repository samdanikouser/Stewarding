import { Printer } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { useAuth } from '@/lib/auth'
import { fmtDate } from '@/lib/format'
import { qs, useApi } from '@/lib/useApi'
import { useAllItems } from '@/lib/useItems'

interface Limit { item_id: number; received: number; system_qty: number }

/** A paper sheet to count from: the items of one location in shelf or category order, with a box for the counted quantity. */
export function CountSheetPage() {
  const { me } = useAuth()
  const [params] = useSearchParams()
  const locationId = Number(params.get('location_id')) || null
  const [group, setGroup] = useState<'storage' | 'category'>('storage')
  const [showSystem, setShowSystem] = useState(false)  // a blind count is more honest, so the book figure is off by default
  const [onlyHere, setOnlyHere] = useState(params.get('all') !== '1')  // a round counts every item that exists, so its sheet lists them all
  const { items } = useAllItems()
  const limits = useApi<Limit[]>(locationId ? `/stock/count-limits${qs({ location_id: locationId })}` : null).data
  const org = useApi<{ name: string }>('/organization').data
  const place = me?.locations.find((l) => l.id === locationId)?.name ?? ''
  const limitOf = useMemo(() => new Map((limits ?? []).map((l) => [l.item_id, l])), [limits])

  const groups = useMemo(() => {
    const keep = items.filter((i) => !onlyHere || !limits || (limitOf.get(i.id)?.received ?? 0) > 0 || (limitOf.get(i.id)?.system_qty ?? 0) > 0)
    const by = new Map<string, typeof items>()
    for (const item of keep) {
      const key = (group === 'storage' ? item.storage_location : item.category)?.trim() || (group === 'storage' ? 'No storage area set' : 'Uncategorised')
      by.set(key, [...(by.get(key) ?? []), item])
    }
    return [...by].sort(([a], [b]) => (a.startsWith('No storage') ? 1 : b.startsWith('No storage') ? -1 : a.localeCompare(b)))
      .map(([name, rows]) => [name, rows.sort((x, y) => x.name.localeCompare(y.name))] as const)
  }, [items, limits, limitOf, group, onlyHere])

  return (
    <div className="mx-auto max-w-4xl bg-white p-6 text-black print:max-w-none print:p-0">
      <div className="mb-4 flex flex-wrap items-center gap-3 print:hidden">
        <Select aria-label="Order by" className="w-auto" value={group} onChange={(e) => setGroup(e.target.value as 'storage' | 'category')}>
          <option value="storage">Sorted by storage area</option>
          <option value="category">Sorted by category</option>
        </Select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyHere} onChange={(e) => setOnlyHere(e.target.checked)} /> Only items held here</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showSystem} onChange={(e) => setShowSystem(e.target.checked)} /> Show the system quantity</label>
        <Button onClick={() => window.print()}><Printer className="h-4 w-4" /> Print</Button>
      </div>

      <header className="mb-4 space-y-1 border-b border-black pb-3">
        <p className="text-sm">{org?.name}</p>
        <h1 className="text-2xl font-bold">Stock count sheet: {place}</h1>
        <p className="text-sm">Printed {fmtDate(new Date().toISOString().slice(0, 10))}. Counted by ______________________ Date ______________ Checked by ______________________</p>
      </header>

      {groups.length === 0 && <p className="text-sm">Nothing to count{locationId ? '' : ': open this from a count round, using Print count sheet'}.</p>}
      {groups.map(([name, rows]) => (
        <section key={name} className="mb-5">
          <h2 className="border-b border-black text-base font-bold">{name} <span className="text-sm font-normal">({rows.length})</span></h2>
          <table className="w-full border-collapse text-sm">
            <thead className="table-header-group">
              <tr className="text-left text-xs uppercase"><th className="w-24 py-1">Code</th><th>Item</th><th className="w-16">Unit</th>{showSystem && <th className="w-20 text-right">System</th>}<th className="w-28 text-center">Counted</th><th className="w-40">Notes</th></tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id} className="break-inside-avoid border-b border-neutral-400">
                  <td className="py-2 tabular-nums">{i.code}</td><td>{i.name}</td><td>{i.unit}</td>
                  {showSystem && <td className="text-right tabular-nums">{limitOf.get(i.id)?.system_qty ?? 0}</td>}
                  <td className="px-2"><div className="h-7 border border-black" /></td><td><div className="h-7 border-b border-neutral-500" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  )
}
