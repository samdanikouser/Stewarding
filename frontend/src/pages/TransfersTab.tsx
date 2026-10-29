import { Check, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AssetTagPicker } from '@/components/AssetTagPicker'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDateTime } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { useAllItems } from '@/lib/useItems'
import { ItemPicker } from '@/components/ItemPicker'
import { useLineEntry } from '@/lib/useLineEntry'
import { iso } from '@/lib/dates'

interface Transfer {
  id: number
  from_location_id: number
  to_location_id: number
  status: string
  requested_by: number
  requested_at: string
  note: string | null
  lines: { item_id: number; qty: number; asset_tags: string[]; unit_cost: number | null; value: number | null }[]
  total_value: number
}

const money = (n: number) => n.toLocaleString('en-GB', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

export function TransfersTab() {
  const { me } = useAuth()
  const run = useRun()
  const canApprove = me?.permissions.includes('stock.approve') ?? false
  const { data, reload } = useApi<Transfer[]>('/stock/transfers')
  const destinations = useApi<{ id: number; name: string }[]>('/stock/locations')
  const { items, byId } = useAllItems()
  const [params] = useSearchParams()
  const [from, setFrom] = useState(params.get('from') ?? String(me?.locations[0]?.id ?? ''))
  const [to, setTo] = useState(params.get('to') ?? '')
  const [note, setNote] = useState('')
  const [catchUp, setCatchUp] = useState(false)  // the stock was moved by hand earlier and is only being recorded now
  const [movedOn, setMovedOn] = useState(() => iso(new Date(Date.now() - 86400000)))
  const [pasted, setPasted] = useState<string | null>(null)  // null: the paste box is closed
  const [pasteMsg, setPasteMsg] = useState('')
  const suggested = params.get('item') ? { item: params.get('item') ?? '', qty: params.get('qty') ?? '', tags: [] as number[] } : undefined
  const entry = useLineEntry({ item: '', qty: '', tags: [] as number[] }, (l) => l.item !== '' && Number(l.qty) > 0, suggested)
  const { attachList } = entry
  const places = new Map(destinations.data?.map((l) => [l.id, l.name]))
  const stock = useApi<{ item_id: number; qty: number; avg_cost: number | null }[]>(from ? `/stock/location-stock${qs({ location_id: from })}` : null)
  const held = new Map((stock.data ?? []).map((s) => [s.item_id, s]))
  const asked = new Map<number, number>()
  for (const l of entry.rows) if (l.item && Number(l.qty) > 0) asked.set(Number(l.item), (asked.get(Number(l.item)) ?? 0) + Number(l.qty))
  const available = (id: number) => held.get(id)?.qty ?? 0
  const over = [...asked].some(([id, qty]) => qty > available(id))
  const lineValue = (l: { item: string; qty: string }) => (l.item && Number(l.qty) > 0 && held.get(Number(l.item))?.avg_cost != null ? Number(l.qty) * held.get(Number(l.item))!.avg_cost! : null)
  const tracked = (l: { item: string }) => byId.get(Number(l.item))?.is_tracked_asset ?? false
  const tagsMissing = entry.rows.some((l) => l.item && Number(l.qty) > 0 && tracked(l) && l.tags.length !== Number(l.qty))
  const total = entry.rows.reduce((sum, l) => sum + (lineValue(l) ?? 0), 0)

  async function request() {
    const ok = await run(() => api('/stock/transfers', { body: {
      from_location_id: Number(from), to_location_id: Number(to), note: note || null, ...(catchUp ? { moved_on: movedOn } : {}),
      lines: entry.rows.filter((l) => l.item && l.qty).map((l) => ({ item_id: Number(l.item), qty: Number(l.qty), asset_ids: tracked(l) ? l.tags : [] })),
    } }), catchUp ? 'Catch-up transfer recorded' : canApprove ? 'Transfer completed' : 'Transfer requested - awaiting approval')
    if (ok) {
      entry.reset()
      setNote('')
      setPasted(null)
      reload()
    }
  }

  /** Turns a pasted list ("PL-001 24" or "PL-001, 24" per line) into transfer lines, and says which codes were not found. */
  function applyPaste() {
    const byCode = new Map(items.map((i) => [i.code.toLowerCase(), i]))
    const found = new Map<number, number>()
    const unknown: string[] = []
    for (const line of (pasted ?? '').split('\n').map((l) => l.trim()).filter(Boolean)) {
      const parts = line.split(/[\t,;]+|\s+/).filter(Boolean)
      const qty = Number(parts[parts.length - 1])
      const item = byCode.get((parts[0] ?? '').toLowerCase())
      if (!item || parts.length < 2 || !Number.isInteger(qty) || qty <= 0) unknown.push(parts[0] ?? line)
      else found.set(item.id, (found.get(item.id) ?? 0) + qty)
    }
    entry.load([...found].map(([id, qty]) => ({ item: String(id), qty: String(qty), tags: [] as number[] })))
    setPasteMsg(`${found.size} line(s) added.${unknown.length ? ` Not understood: ${unknown.slice(0, 6).join(', ')}${unknown.length > 6 ? '...' : ''}` : ''}`)
    if (unknown.length === 0) setPasted(null)
  }

  async function decide(id: number, approve: boolean) {
    if (await run(() => api(`/stock/transfers/${id}/decision`, { body: { approve } }), approve ? 'Transfer approved' : 'Transfer rejected')) reload()
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>New transfer</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="From"><Select value={from} onChange={(e) => setFrom(e.target.value)}>{me?.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</Select></Field>
            <Field label="To">
              <Select value={to} onChange={(e) => setTo(e.target.value)}>
                <option value="">Select</option>
                {destinations.data?.filter((l) => String(l.id) !== from).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </Select>
            </Field>
          </div>
          <div ref={attachList} className="space-y-2">
            {entry.rows.map((line, i) => (
              <div key={i} {...entry.rowProps(i)} className="flex flex-wrap items-end gap-2">
                <Field label={i === 0 ? 'Item' : ''}>
                  <ItemPicker className="w-64" items={items} value={line.item} onChange={(id) => entry.update(i, { item: id, tags: [] })} />
                </Field>
                <Field label={i === 0 ? 'Qty' : ''}><Input aria-label="Quantity" type="number" min={1} className="w-24" value={line.qty} onChange={(e) => entry.update(i, { qty: e.target.value, tags: line.tags.slice(0, Number(e.target.value) || 0) })} /></Field>
                <Field label={i === 0 ? 'Available' : ''}><output aria-label="Available" className="flex h-10 w-20 items-center justify-end text-sm tabular-nums">{line.item ? available(Number(line.item)) : '-'}</output></Field>
                <Field label={i === 0 ? 'Unit cost' : ''}><output aria-label="Unit cost" className="flex h-10 w-20 items-center justify-end text-sm tabular-nums">{line.item && held.get(Number(line.item))?.avg_cost != null ? money(held.get(Number(line.item))!.avg_cost!) : '-'}</output></Field>
                <Field label={i === 0 ? 'Value' : ''}><output aria-label="Line value" className="flex h-10 w-24 items-center justify-end text-sm font-medium tabular-nums">{lineValue(line) != null ? money(lineValue(line)!) : '-'}</output></Field>
                <span className="flex h-10 w-5 items-center text-ok" aria-label={line.committed ? 'Line saved' : undefined}>{line.committed && <Check className="h-4 w-4" aria-hidden />}</span>
                {entry.rows.length > 1 && <Button variant="ghost" size="icon" aria-label="Remove line" onClick={() => entry.remove(i)}><Trash2 className="h-4 w-4" /></Button>}
                {line.item && Number(line.qty) > 0 && tracked(line) && (
                  <AssetTagPicker itemId={Number(line.item)} locationId={Number(from)} qty={Number(line.qty)} value={line.tags} onChange={(tags) => entry.update(i, { tags })} />
                )}
                {entry.incomplete === i && <p role="alert" className="w-full text-xs text-danger">Choose an item and a quantity, then press Enter.</p>}
                {line.item && (asked.get(Number(line.item)) ?? 0) > available(Number(line.item)) && (
                  <p role="alert" className="w-full text-xs font-medium text-danger">
                    Only {available(Number(line.item))} in stock here but {asked.get(Number(line.item))} asked for. Something is wrong: check the quantity. It cannot be transferred.
                  </p>
                )}
              </div>
            ))}
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="outline" size="sm" onClick={entry.addRow}><Plus className="h-4 w-4" /> Add line</Button>
              <Button variant="outline" size="sm" onClick={() => setPasted((p) => (p === null ? '' : null))}>Paste a list</Button>
              {pasteMsg && <span className="text-xs text-ink-muted">{pasteMsg}</span>}
            </div>
            {pasted !== null && (
              <div className="space-y-2 rounded-lg border border-border bg-surface-muted/50 p-3">
                <Field label="One item per line: the item code, then the quantity (for example PL-001 24)">
                  <textarea aria-label="Pasted list" rows={6} className="w-full rounded-lg border border-border-strong bg-surface p-2 text-sm" value={pasted} onChange={(e) => setPasted(e.target.value)} />
                </Field>
                <Button size="sm" disabled={!pasted.trim()} onClick={applyPaste}>Add these lines</Button>
              </div>
            )}
          </div>
          <p className="text-right text-sm">Total value <span className="ml-2 text-base font-semibold tabular-nums">{money(total)}</span></p>
          {canApprove && (
            <div className="space-y-2 rounded-lg border border-border px-3 py-2">
              <label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" checked={catchUp} onChange={(e) => setCatchUp(e.target.checked)} /> The stock was already moved (a catch-up)</label>
              {catchUp && (
                <div className="space-y-1">
                  <Field label="Date it was moved"><Input aria-label="Date it was moved" type="date" className="w-auto" max={iso(new Date())} min={iso(new Date(Date.now() - 90 * 86400000))} value={movedOn} onChange={(e) => setMovedOn(e.target.value)} /></Field>
                  <p className="text-xs text-ink-muted">Records the move on that date, up to 90 days back, and updates both locations at once. It cannot be dated before a count already posted at either place.</p>
                </div>
              )}
            </div>
          )}
          <Field label="Note"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <Button disabled={!to || over || tagsMissing || (catchUp && !movedOn) || !entry.rows.some((l) => l.item && l.qty)} onClick={request}>{catchUp ? 'Record the move' : canApprove ? 'Transfer now' : 'Request transfer'}</Button>
        </CardContent>
      </Card>

      <h2 className="text-lg font-semibold">Transfers</h2>
      {data?.length === 0 && <EmptyState title="No transfers yet" />}
      <ul className="space-y-2">
        {data?.map((t) => (
          <li key={t.id} className="rounded-lg border border-border bg-surface p-4 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">#{t.id}: {places.get(t.from_location_id) ?? t.from_location_id} to {places.get(t.to_location_id) ?? t.to_location_id}</span>
              <StatusBadge status={t.status} />
            </div>
            <ul className="mt-1 text-ink-muted">
              {t.lines.map((l) => <li key={l.item_id}>{l.qty} x {byId.get(l.item_id)?.name ?? l.item_id}{l.asset_tags.length > 0 && <span> ({l.asset_tags.join(', ')})</span>}{l.value != null && <span> - {money(l.value)}</span>}</li>)}
            </ul>
            <p className="text-ink-muted">{fmtDateTime(t.requested_at)}{t.total_value > 0 && <span> - total {money(t.total_value)}</span>}</p>
            {t.status === 'requested' && canApprove && t.requested_by !== me?.id && (
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => decide(t.id, true)}>Approve</Button>
                <Button size="sm" variant="danger" onClick={() => decide(t.id, false)}>Reject</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
