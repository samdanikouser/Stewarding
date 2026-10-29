import { useState, type FormEvent } from 'react'
import { WorkLocationSelect } from '@/components/WorkLocationSelect'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { fmtDateTime } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { LabelActions } from '@/pages/trace/LabelActions'
import { RECEIVED_CONDITIONS, type Lot } from '@/pages/trace/types'

interface FoodItem {
  id: number
  name: string
  food_group: string
  group_label: string
}

const QTY_UNITS = ['kg', 'g', 'l', 'ml', 'pcs', 'cases', 'packs']

const BLANK = { item: '', condition: 'chilled_raw', supplier: '', supplier_lot: '', produced_on: '', expiry_on: '', temp_c: '', qty: '', unit: '', tag_number: '', note: '' }

export function ReceiveLotForm({ onSaved }: { onSaved: () => void }) {
  const run = useRun()
  const foods = useApi<FoodItem[]>('/lots/food-items')
  const suppliers = useApi<{ id: number; name: string }[]>('/lots/suppliers')
  const [locationId, setLocationId] = useState<number | null>(null)
  const [form, setForm] = useState(BLANK)
  const [made, setMade] = useState<Lot | null>(null)
  const set = (key: keyof typeof BLANK, value: string) => setForm((f) => ({ ...f, [key]: value }))
  const group = foods.data?.find((f) => String(f.id) === form.item)?.food_group

  async function save(event: FormEvent) {
    event.preventDefault()
    let lot: Lot | null = null
    const ok = await run(async () => {
      lot = await api<Lot>('/lots', { body: {
        food_item_id: Number(form.item), location_id: locationId, condition: form.condition, supplier_id: Number(form.supplier),
        supplier_lot: form.supplier_lot, produced_on: form.produced_on || null, expiry_on: form.expiry_on || null,
        temp_c: form.temp_c !== '' ? Number(form.temp_c) : null, qty: form.qty !== '' ? Number(form.qty) : null, unit: form.unit || null,
        tag_number: form.tag_number || null, note: form.note || null,
      } })
    }, 'Lot created')
    if (ok && lot) {
      setMade(lot)
      onSaved()
    }
  }

  if (!foods.data) return <Skeleton className="h-48 w-full" />
  if (made) {
    return (
      <div className="space-y-4 rounded-xl border border-border bg-surface p-5">
        {made.status === 'on_hold' && (
          <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm font-semibold text-danger">
            This delivery arrived too warm and is on hold. Keep it apart and do not use it until a manager releases it.
          </p>
        )}
        <p className="text-3xl font-semibold tracking-wide">{made.code}</p>
        <p className="text-sm">{made.item}{made.supplier ? ` from ${made.supplier}` : ''}. Use by <span className="font-semibold">{made.use_by ? fmtDateTime(made.use_by) : 'not set'}</span>.</p>
        {!made.use_by && <p className="text-sm text-warn">No expiry date was entered and no shelf-life rule applies, so this lot has no use-by date.</p>}
        <LabelActions ids={[made.id]} />
        <Button type="button" variant="outline" onClick={() => { setMade(null); setForm(BLANK) }}>Receive another</Button>
      </div>
    )
  }
  if (foods.data.length === 0) return <p className="text-sm text-ink-muted">No food items yet. Ask a manager to add them under Food items.</p>

  return (
    <form onSubmit={save} className="max-w-3xl space-y-4 rounded-xl border border-border bg-surface p-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Food item">
          <Select required value={form.item} onChange={(e) => set('item', e.target.value)}>
            <option value="">Select a food item</option>
            {foods.data.map((f) => <option key={f.id} value={f.id}>{f.name} ({f.group_label})</option>)}
          </Select>
        </Field>
        <WorkLocationSelect label="Received at" fill value={locationId} onChange={setLocationId} />
        <Field label="How it arrived">
          <Select value={form.condition} onChange={(e) => set('condition', e.target.value)}>
            {RECEIVED_CONDITIONS.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
          </Select>
        </Field>
        <Field label="Supplier">
          <Select required value={form.supplier} onChange={(e) => set('supplier', e.target.value)}>
            <option value="">{suppliers.data?.length === 0 ? 'No suppliers yet' : 'Select a supplier'}</option>
            {suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field label="Supplier lot or batch number"><Input required maxLength={60} value={form.supplier_lot} onChange={(e) => set('supplier_lot', e.target.value)} /></Field>
        <Field label="Temperature on arrival (C)"><Input type="number" step="0.1" value={form.temp_c} onChange={(e) => set('temp_c', e.target.value)} /></Field>
        <Field label="Production date"><Input type="date" value={form.produced_on} onChange={(e) => set('produced_on', e.target.value)} /></Field>
        <Field label="Expiry date"><Input type="date" min={form.produced_on || undefined} value={form.expiry_on} onChange={(e) => set('expiry_on', e.target.value)} /></Field>
        <Field label="Quantity received"><Input type="number" min={0} step="any" value={form.qty} onChange={(e) => set('qty', e.target.value)} /></Field>
        <Field label="Unit">
          <Select required={form.qty !== ''} value={form.unit} onChange={(e) => set('unit', e.target.value)}>
            <option value="">Select</option>
            {QTY_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </Select>
        </Field>
        {group === 'seafood' && <Field label="Shellfish or harvest tag number"><Input maxLength={60} value={form.tag_number} onChange={(e) => set('tag_number', e.target.value)} /></Field>}
        <Field label="Note (optional)"><Input maxLength={500} value={form.note} onChange={(e) => set('note', e.target.value)} /></Field>
      </div>
      <Button type="submit" disabled={!form.item || !form.supplier || !form.supplier_lot.trim() || locationId === null}>Create lot and label</Button>
    </form>
  )
}
