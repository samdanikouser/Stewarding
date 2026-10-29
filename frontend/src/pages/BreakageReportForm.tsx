import { useState, type FormEvent } from 'react'
import { WorkLocationSelect } from '@/components/WorkLocationSelect'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Plus, Trash2 } from 'lucide-react'
import { Select } from '@/components/ui/select'
import { api, uploadFile } from '@/lib/api'
import { useRun } from '@/lib/toast'
import { useAllItems } from '@/lib/useItems'
import { ItemPicker } from '@/components/ItemPicker'
import { qs, useApi } from '@/lib/useApi'
import { useLookup } from '@/lib/useLookups'

const OTHER = '__other__'
const money = (n: number) => n.toLocaleString('en-GB', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

export function BreakageReportForm({ onSaved }: { onSaved: () => void }) {
  const run = useRun()
  const { items } = useAllItems()
  const [locationId, setLocationId] = useState<number | null>(null)
  const [lines, setLines] = useState([{ item: '', qty: '1' }])
  const [type, setType] = useState('breakage')
  const reasons = useLookup('breakage_reason')
  const [reasonChoice, setReasonChoice] = useState('')
  const [reason, setReason] = useState('')
  const [description, setDescription] = useState('')
  const [file, setFile] = useState<File | null>(null)

  // prices come from the average cost at the location; people who may not see costs get no prices
  const stock = useApi<{ item_id: number; avg_cost: number | null }[]>(locationId ? `/stock/location-stock${qs({ location_id: locationId })}` : null)
  const cost = new Map((stock.data ?? []).map((s) => [s.item_id, s.avg_cost]))
  const priced = stock.data !== undefined
  const worth = (l: { item: string; qty: string }) => (l.item && Number(l.qty) > 0 && cost.get(Number(l.item)) != null ? Number(l.qty) * cost.get(Number(l.item))! : null)
  const total = lines.reduce((sum, l) => sum + (worth(l) ?? 0), 0)
  const patch = (index: number, change: Partial<{ item: string; qty: string }>) => setLines((all) => all.map((l, n) => (n === index ? { ...l, ...change } : l)))
  const complete = lines.every((l) => l.item && Number(l.qty) >= 1) && new Set(lines.map((l) => l.item)).size === lines.length

  async function submit(event: FormEvent) {
    event.preventDefault()
    const ok = await run(async () => {
      const photo = file ? await uploadFile(file) : null
      await api('/breakage/batch', { body: {
        location_id: locationId, incident_type: type, reason: reason || null, description: description || null, photo_path: photo,
        lines: lines.map((l) => ({ item_id: Number(l.item), qty: Number(l.qty) })),
      } })
    }, lines.length > 1 ? 'Incidents reported - your supervisor has been notified' : 'Incident reported - your supervisor has been notified')
    if (ok) {
      setLines([{ item: '', qty: '1' }])
      setReasonChoice('')
      setReason('')
      setDescription('')
      setFile(null)
      onSaved()
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <WorkLocationSelect label="Location" fill value={locationId} onChange={setLocationId} />
        <Field label="Incident type">
          <Select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="breakage">Breakage</option>
            <option value="damage">Damage</option>
            <option value="missing">Missing</option>
            <option value="written_off">Written off</option>
          </Select>
        </Field>
      </div>
      <div className="space-y-2">
        <div aria-hidden className="hidden grid-cols-[minmax(12rem,1fr)_5rem_5.5rem_6rem_2.5rem] gap-2 text-sm font-medium sm:grid">
          <span>Item</span><span>Quantity</span><span className="text-right">{priced ? 'Unit cost' : ''}</span><span className="text-right">{priced ? 'Value' : ''}</span><span />
        </div>
        {lines.map((l, i) => (
          <div key={i} className="grid grid-cols-[1fr_4.5rem_2.5rem] items-center gap-2 sm:grid-cols-[minmax(12rem,1fr)_5rem_5.5rem_6rem_2.5rem]">
            <ItemPicker items={items} value={l.item} onChange={(id) => patch(i, { item: id })} />
            <Input aria-label="Quantity" required type="number" min={1} inputMode="numeric" value={l.qty} onChange={(e) => patch(i, { qty: e.target.value })} />
            <div className="order-2 col-span-3 flex justify-between text-sm sm:contents">
              <output aria-label="Unit cost" className="text-sm tabular-nums sm:text-right">{priced && l.item && cost.get(Number(l.item)) != null ? <><span className="text-ink-muted sm:hidden">Unit cost </span>{money(cost.get(Number(l.item))!)}</> : ''}</output>
              <output aria-label="Line value" className="text-sm font-medium tabular-nums sm:text-right">{priced && worth(l) != null ? <><span className="font-normal text-ink-muted sm:hidden">Value </span>{money(worth(l)!)}</> : ''}</output>
            </div>
            {lines.length > 1 ? <Button type="button" variant="ghost" size="icon" className="order-1 sm:order-none" aria-label="Remove item" onClick={() => setLines((all) => all.filter((_, n) => n !== i))}><Trash2 className="h-4 w-4" /></Button> : <span className="order-1 sm:order-none" />}
          </div>
        ))}
        {new Set(lines.map((l) => l.item).filter(Boolean)).size < lines.filter((l) => l.item).length && <p role="alert" className="text-xs text-danger">An item appears twice; add the quantities together.</p>}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button type="button" variant="outline" size="sm" onClick={() => setLines((all) => [...all, { item: '', qty: '1' }])}><Plus className="h-4 w-4" /> Add another item</Button>
          {priced && <p className="text-sm">Total breakage value <span className="ml-2 text-base font-semibold tabular-nums">{money(total)}</span></p>}
        </div>
      </div>
      <Field label="What happened?">
        <Select value={reasonChoice} onChange={(e) => { setReasonChoice(e.target.value); if (e.target.value !== OTHER) setReason(e.target.value) }}>
          <option value="">Select a reason</option>
          {reasons.map((r) => <option key={r} value={r}>{r}</option>)}
          <option value={OTHER}>Other (describe)</option>
        </Select>
      </Field>
      {reasonChoice === OTHER && <Field label="Describe the cause"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
      <Field label="Description (optional)"><Input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Photo (optional)"><Input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
      <Button type="submit" className="w-full sm:w-auto" disabled={!locationId || !complete}>Report {lines.length > 1 ? `${lines.length} items` : 'incident'}</Button>
    </form>
  )
}
