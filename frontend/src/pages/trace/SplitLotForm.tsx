import { Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { LotPicker, type LotChoice } from '@/components/LotPicker'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { api } from '@/lib/api'
import { fmtDate, fmtDateTime } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { amountText, cutTotal, cutsUse } from '@/lib/units'
import { useApi } from '@/lib/useApi'
import { LabelActions } from '@/pages/trace/LabelActions'
import type { PortionName } from '@/pages/trace/PortionNamesTab'
import { RECEIVED_CONDITIONS, type Lot, type Trace } from '@/pages/trace/types'

const SIZE_UNITS = ['g', 'kg', 'ml', 'l', 'pcs']

const blank = () => ({ name: '', size: '', unit: 'g', count: '1', condition: 'vacuum_chilled', waste: '' })

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-surface-muted px-3 py-2">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className={`text-base font-semibold tabular-nums ${tone ?? ''}`}>{value}</dd>
    </div>
  )
}

export function SplitLotForm({ onSaved }: { onSaved: () => void }) {
  const run = useRun()
  const [chosen, setChosen] = useState<LotChoice[]>([])
  const [parts, setParts] = useState([blank()])
  const [finish, setFinish] = useState(false)
  const [made, setMade] = useState<Lot[] | null>(null)
  const trace = useApi<Trace>(chosen[0] ? `/lots/${chosen[0].id}` : null).data
  const parent = trace?.lot
  const portionNames = useApi<PortionName[]>('/lots/portion-names').data ?? []
  const suggested = portionNames.filter((n) => n.food_item_id === null || n.food_item_id === parent?.food_item_id)
  const balance = trace?.balance ?? null
  const thawed = parent?.condition === 'thawed'
  const using = balance ? cutsUse(balance, parts) : null
  const over = balance && using ? using.portions + using.waste > balance.left : false
  const patch = (index: number, change: Partial<ReturnType<typeof blank>>) => setParts((all) => all.map((p, n) => (n === index ? { ...p, ...change } : p)))

  async function save(event: FormEvent) {
    event.preventDefault()
    let lots: Lot[] = []
    const ok = await run(async () => {
      const result = await api<{ lots: Lot[] }>(`/lots/${chosen[0].id}/split`, { body: {
        finish_parent: finish,
        parts: parts.map((p) => ({
          description: p.name, count: Number(p.count), condition: thawed ? 'thawed' : p.condition,
          size: Number(p.size), unit: p.unit, waste: p.waste !== '' ? Number(p.waste) : null,
        })),
      } })
      lots = result.lots
    }, 'Portion lots created')
    if (ok) {
      setMade(lots)
      onSaved()
    }
  }

  if (made) {
    return (
      <div className="space-y-4 rounded-xl border border-border bg-surface p-5">
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {made.map((l) => (
            <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span><span className="font-semibold">{l.code}</span> <span className="text-ink-muted">{l.pack_count} x {l.pack_description} ({l.condition_label})</span></span>
              <span>Use by <span className="font-semibold">{l.use_by ? fmtDateTime(l.use_by) : '-'}</span></span>
            </li>
          ))}
        </ul>
        <LabelActions ids={made.map((l) => l.id)} packs={made.reduce((n, l) => n + (l.pack_count ?? 0), 0)} />
        <Button type="button" variant="outline" onClick={() => { setMade(null); setChosen([]); setParts([blank()]); setFinish(false) }}>Split another lot</Button>
      </div>
    )
  }

  return (
    <form onSubmit={save} className="max-w-3xl space-y-4 rounded-xl border border-border bg-surface p-5">
      <Field label="Lot being opened">
        <LotPicker max={1} value={chosen} onChange={setChosen} />
      </Field>
      {parent && (
        <p className="rounded-lg bg-surface-muted p-3 text-sm">
          <span className="font-semibold">{parent.item}</span> from {parent.supplier ?? 'unknown supplier'}, supplier lot {parent.supplier_lot ?? '-'}. Produced {parent.produced_on ? fmtDate(parent.produced_on) : '-'},
          expiry {parent.expiry_on ? fmtDate(parent.expiry_on) : '-'}, use by {parent.use_by ? fmtDateTime(parent.use_by) : '-'}.
        </p>
      )}
      {parent && balance && (
        <div className="space-y-2">
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Received" value={`${balance.qty} ${balance.unit}`} />
            <Stat label="Already portioned" value={`${balance.portioned} ${balance.unit}`} />
            <Stat label="Waste" value={`${balance.waste} ${balance.unit}`} />
            <Stat label="Left to portion" value={`${balance.left} ${balance.unit}`} tone={balance.left <= 0 ? 'text-danger' : 'text-ok'} />
          </dl>
          {balance.unmeasured > 0 && <p className="text-xs text-ink-muted">{balance.unmeasured} earlier portion lot(s) have no comparable quantity and are not counted.</p>}
        </div>
      )}
      {parent && !balance && <p className="text-sm text-ink-muted">No quantity was recorded when this lot was received, so no balance is shown.</p>}
      <datalist id="portion-names">{suggested.map((n) => <option key={n.id} value={n.name} />)}</datalist>
      <div className="space-y-3">
        {parts.map((p, i) => {
          const total = cutTotal(p)
          return (
            <div key={i} className="space-y-3 rounded-lg border border-border p-3">
              <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <Field label="Portion name">
                  <Input required list="portion-names" maxLength={100} placeholder="Pick a name or type a new one" value={p.name} onChange={(e) => patch(i, { name: e.target.value })} />
                </Field>
                <Field label="Stored as">
                  <Select value={thawed ? 'thawed' : p.condition} disabled={thawed} onChange={(e) => patch(i, { condition: e.target.value })}>
                    {thawed ? <option value="thawed">Thawed</option> : RECEIVED_CONDITIONS.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
                  </Select>
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                <Field label="Size of one portion"><Input required type="number" min={0.01} step="any" value={p.size} onChange={(e) => patch(i, { size: e.target.value })} /></Field>
                <Field label="Unit">
                  <Select value={p.unit} onChange={(e) => patch(i, { unit: e.target.value })}>
                    {SIZE_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
                  </Select>
                </Field>
                <Field label="Number of portions"><Input required type="number" min={1} step={1} value={p.count} onChange={(e) => patch(i, { count: e.target.value })} /></Field>
                <Field label="Total">
                  <output aria-label="Total of this cut" className="flex h-10 items-center rounded-lg bg-surface-muted px-3 text-sm font-semibold tabular-nums">{total === null ? '-' : amountText(total, p.unit)}</output>
                </Field>
                <Field label="Waste (optional)"><Input type="number" min={0} step="any" placeholder={`in ${p.unit}`} value={p.waste} onChange={(e) => patch(i, { waste: e.target.value })} /></Field>
              </div>
              {parts.length > 1 && (
                <Button type="button" variant="ghost" size="sm" onClick={() => setParts((all) => all.filter((_, n) => n !== i))}><Trash2 className="h-4 w-4" aria-hidden /> Remove this cut</Button>
              )}
            </div>
          )
        })}
        <Button type="button" variant="outline" size="sm" onClick={() => setParts((all) => [...all, blank()])}><Plus className="h-4 w-4" aria-hidden /> Add another cut</Button>
      </div>
      {balance && using && using.portions + using.waste > 0 && (
        <p className="text-sm text-ink-muted">This split uses {using.portions} {balance.unit} in portions and {using.waste} {balance.unit} in waste.</p>
      )}
      {over && balance && <p role="status" className="text-sm font-semibold text-warn">That is more than the {balance.left} {balance.unit} left. Check the sizes and numbers before you save.</p>}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={finish} onChange={(e) => setFinish(e.target.checked)} /> Nothing is left of the original pack (mark it used up)</label>
      <Button type="submit" disabled={chosen.length === 0}>Create portion lots and labels</Button>
    </form>
  )
}
