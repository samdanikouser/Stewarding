import { Check, Plus, Trash2 } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { WorkLocationSelect } from '@/components/WorkLocationSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState, SkeletonRows, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { iso } from '@/lib/dates'
import { fmtDate, fmtDateTime } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { useAllItems } from '@/lib/useItems'
import { ItemPicker } from '@/components/ItemPicker'
import { useLineEntry } from '@/lib/useLineEntry'
import { useMoney } from '@/lib/money'

interface Doc {
  id: number
  doc_type: 'receipt' | 'supplier_return'
  supplier: string
  supplier_id: number
  location_id: number
  invoice_number: string
  invoice_date: string | null
  received_on: string
  received_at: string
  received_by_name: string | null
  note: string | null
  status: string
  subtotal: number | null
  line_discount_total: number | null
  discount_type: DiscountType | null
  discount_value: number | null
  discount_amount: number | null
  total_discount: number | null
  total: number | null
  void_reason: string | null
  lines?: { item_id: number; code: string; name: string; qty: number; unit_cost: number | null; gross: number | null; discount_type: DiscountType | null; discount_value: number | null; discount_amount: number | null; line_total: number | null }[]
}

type DiscountType = 'amount' | 'percent'

interface Line {
  item: string
  qty: string
  cost: string
  discType: DiscountType
  disc: string
}

interface PriceHint {
  fromSupplier: { price: number; date: string } | null
  last: { price: number; date: string; supplier: string | null } | null
  average: number | null
  start: number | null
}

const BLANK_LINE: Line = { item: '', qty: '', cost: '', discType: 'amount', disc: '' }

const cut = (type: DiscountType, value: string, base: number) => Math.min(base, type === 'percent' ? (base * Number(value || 0)) / 100 : Number(value || 0))
const lineGross = (l: Line) => Number(l.qty || 0) * Number(l.cost || 0)
const lineComplete = (l: Line) => l.item !== '' && Number(l.qty) > 0

const SIZE = 10
const LABEL = { receipt: 'Goods receipt', supplier_return: 'Return to supplier' }

export function ReceivingTab() {
  const money = useMoney()
  const { me } = useAuth()
  const run = useRun()
  const canVoid = me?.permissions.includes('stock.approve') ?? false
  const { items } = useAllItems()
  const suppliers = useApi<{ id: number; name: string }[]>('/suppliers')
  const [filterSupplier, setFilterSupplier] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [search, setSearch] = useState('')
  const [filterFrom, setFilterFrom] = useState('')
  const [filterTo, setFilterTo] = useState('')
  const [dateBy, setDateBy] = useState<'invoice' | 'received'>('invoice')
  const [page, setPage] = useState(1)
  const list = useApi<{ total: number; items: Doc[] }>(
    `/receipts${qs({ supplier_id: filterSupplier, receipt_status: filterStatus, q: search, date_from: filterFrom, date_to: filterTo, date_by: dateBy, page, size: SIZE })}`,
  )
  const places = new Map(me?.locations.map((l) => [l.id, l.name]))

  const [docType, setDocType] = useState<'receipt' | 'supplier_return'>('receipt')
  const [supplierId, setSupplierId] = useState('')
  const [locationId, setLocationId] = useState<number | null>(null)
  const [invoice, setInvoice] = useState('')
  const [receivedOn, setReceivedOn] = useState(() => iso(new Date()))
  const [invoiceDate, setInvoiceDate] = useState(() => iso(new Date()))  // follows the received date until it is changed by hand
  const [invoiceDateTouched, setInvoiceDateTouched] = useState(false)
  const [note, setNote] = useState('')
  const [docDiscType, setDocDiscType] = useState<DiscountType>('amount')
  const [docDisc, setDocDisc] = useState('')
  const entry = useLineEntry<Line>(BLANK_LINE, lineComplete)
  const { attachList } = entry
  const [detail, setDetail] = useState<Doc | null>(null)
  const [voiding, setVoiding] = useState(false)
  const [voidReason, setVoidReason] = useState('')
  const [editing, setEditing] = useState<Doc | null>(null)
  const [correcting, setCorrecting] = useState<Doc | null>(null)  // a posted invoice whose items are being fixed in the form above
  const [reason, setReason] = useState('')
  const [edit, setEdit] = useState({ invoice: '', invoiceDate: '', receivedOn: '', note: '' })

  // what was paid before, kept per item so the line can say where its price came from and offer the others
  const [hints, setHints] = useState<Record<string, PriceHint>>({})
  const supplierName = suppliers.data?.find((s) => String(s.id) === supplierId)?.name ?? null
  const usual = useMemo(() => new Set(items.filter((it) => supplierId !== '' && (String(it.supplier_id) === supplierId || it.supplier_ids?.includes(Number(supplierId)))).map((it) => it.id)), [items, supplierId])

  /** The price filled in on a picked item: the last paid to this supplier, else the last paid to anyone, else the average, else the starting price. */
  async function pickItem(i: number, id: string) {
    entry.update(i, { item: id, cost: '' })
    const item = items.find((x) => String(x.id) === id)
    if (!item) return
    const history = await api<{ points: { price: number; date: string; supplier: string | null }[] }>(`/inventory/items/${id}/price-history`).catch(() => null)
    const points = history?.points ?? []
    const last = points.at(-1) ?? null
    const fromSupplier = supplierName ? [...points].reverse().find((p) => p.supplier === supplierName) ?? null : null
    const hint: PriceHint = { fromSupplier, last, average: item.avg_cost ?? null, start: item.unit_cost ?? null }
    setHints((all) => ({ ...all, [id]: hint }))
    const price = fromSupplier?.price ?? last?.price ?? hint.average ?? hint.start
    if (price != null) entry.patchIf(i, (r) => r.item === id && r.cost === '', { cost: String(price) })
  }
  const filled = entry.rows.filter(lineComplete)
  const subtotal = filled.reduce((sum, l) => sum + lineGross(l), 0)
  const lineDiscounts = filled.reduce((sum, l) => sum + cut(l.discType, l.disc, lineGross(l)), 0)
  const docDiscount = cut(docDiscType, docDisc, subtotal - lineDiscounts)
  const total = subtotal - lineDiscounts - docDiscount
  const hasCosts = filled.some((l) => l.cost !== '')

  function clearForm() {
    setInvoice('')
    setReceivedOn(iso(new Date()))
    setInvoiceDate(iso(new Date()))
    setInvoiceDateTouched(false)
    setNote('')
    setDocDisc('')
    setCorrecting(null)
    setReason('')
    entry.reset()
  }

  /** Puts a posted invoice back in the form, lines and all, so its items, quantities and prices can be fixed. */
  function startCorrection(doc: Doc) {
    setCorrecting(doc)
    setReason('')
    setDocType(doc.doc_type)
    setSupplierId(String(doc.supplier_id))
    setLocationId(doc.location_id)
    setInvoice(doc.invoice_number)
    setReceivedOn(doc.received_on)
    setInvoiceDate(doc.invoice_date ?? '')
    setInvoiceDateTouched(true)
    setNote(doc.note ?? '')
    setDocDiscType(doc.discount_type ?? 'amount')
    setDocDisc(doc.discount_value != null ? String(doc.discount_value) : '')
    entry.load((doc.lines ?? []).map((l) => ({ item: String(l.item_id), qty: String(l.qty), cost: l.unit_cost != null ? String(l.unit_cost) : '',
      discType: l.discount_type ?? 'amount', disc: l.discount_value != null ? String(l.discount_value) : '' })))
    setDetail(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function correct(doc: Doc) {
    startCorrection(await api<Doc>(`/receipts/${doc.id}`))
  }

  async function post() {
    const body = {
      doc_type: docType, supplier_id: Number(supplierId), location_id: locationId, invoice_number: invoice,
      invoice_date: invoiceDate || null, received_on: receivedOn || null, note: note || null,
      discount_type: docDisc ? docDiscType : null, discount: docDisc ? Number(docDisc) : null,
      lines: filled.map((l) => ({
        item_id: Number(l.item), qty: Number(l.qty), unit_cost: l.cost === '' ? null : Number(l.cost),
        discount_type: l.disc ? l.discType : null, discount: l.disc ? Number(l.disc) : null,
      })),
    }
    if (correcting) {
      if (await run(() => api(`/receipts/${correcting.id}/correct`, { body: { ...body, reason } }), 'Invoice corrected and stock adjusted')) {
        clearForm()
        list.reload()
      }
      return
    }
    const ok = await run(() => api('/receipts', { body }), docType === 'receipt' ? 'Delivery received and stock updated' : 'Return posted and stock reduced')
    if (ok) {
      clearForm()
      list.reload()
    }
  }

  async function open(doc: Doc) {
    setDetail(await api<Doc>(`/receipts/${doc.id}`))
  }

  function startEdit(doc: Doc) {
    setEditing(doc)
    setEdit({ invoice: doc.invoice_number, invoiceDate: doc.invoice_date ?? '', receivedOn: doc.received_on, note: doc.note ?? '' })
  }

  async function saveEdit(event: FormEvent) {
    event.preventDefault()
    if (!editing) return
    const ok = await run(async () => {
      const saved = await api<Doc>(`/receipts/${editing.id}`, { method: 'PUT', body: {
        invoice_number: edit.invoice, invoice_date: edit.invoiceDate || null, received_on: edit.receivedOn, note: edit.note || null,
      } })
      setDetail((current) => (current && current.id === saved.id ? saved : current))
    }, 'Document updated')
    if (ok) {
      setEditing(null)
      list.reload()
    }
  }

  async function voidDoc() {
    if (!detail) return
    const ok = await run(() => api(`/receipts/${detail.id}/void`, { body: { reason: voidReason } }), 'Document voided and stock reversed')
    if (ok) {
      setVoiding(false)
      setVoidReason('')
      setDetail(null)
      list.reload()
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{correcting ? `Correct invoice ${correcting.invoice_number}` : 'New receiving document'}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {correcting && (
            <div role="status" className="space-y-2 rounded-lg border border-warn/40 bg-warn-soft px-4 py-3 text-sm">
              <p>Fix the items, quantities, prices or dates below. The original document is reversed and replaced by the corrected one in one step, and both stay in the history.</p>
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Why is it being corrected?"><Input aria-label="Reason for the correction" className="w-72" minLength={5} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
                <Button type="button" variant="outline" onClick={clearForm}>Cancel the correction</Button>
              </div>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Document">
              <Select value={docType} onChange={(e) => setDocType(e.target.value as typeof docType)}>
                <option value="receipt">Goods receipt (delivery in)</option>
                <option value="supplier_return">Return to supplier (stock out)</option>
              </Select>
            </Field>
            <Field label="Supplier">
              <Select required value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
                <option value="">Select supplier</option>
                {suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            </Field>
            <WorkLocationSelect label="Location" fill value={locationId} onChange={setLocationId} />
            <Field label={docType === 'receipt' ? 'Invoice number' : 'Credit note number'}><Input value={invoice} onChange={(e) => setInvoice(e.target.value)} /></Field>
            <Field label="Received on"><Input type="date" max={iso(new Date())} value={receivedOn} onChange={(e) => { setReceivedOn(e.target.value); if (!invoiceDateTouched) setInvoiceDate(e.target.value) }} /></Field>
            <Field label="Invoice date"><Input type="date" max={iso(new Date())} value={invoiceDate} onChange={(e) => { setInvoiceDate(e.target.value); setInvoiceDateTouched(true) }} /></Field>
            <div className="sm:col-span-2"><Field label="Note"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field></div>
          </div>
          {suppliers.data?.length === 0 && <p className="text-sm text-warn">No suppliers yet. A manager adds them under Settings, Suppliers.</p>}

          <div ref={attachList} className="space-y-2">
            <div className="overflow-x-auto">
              <div className="min-w-[46rem] space-y-2">
                <div aria-hidden className="grid grid-cols-[minmax(14rem,1fr)_6rem_6rem_11rem_6rem_1.25rem_2.5rem] items-end gap-2 text-sm font-medium">
                  <span>Item</span><span>Quantity</span><span>Unit cost</span><span>Discount</span><span className="text-right">Line total</span><span /><span />
                </div>
                {entry.rows.map((line, i) => (
                  <div key={i} {...entry.rowProps(i)} className="space-y-1">
                    <div className="grid grid-cols-[minmax(14rem,1fr)_6rem_6rem_11rem_6rem_1.25rem_2.5rem] items-center gap-2">
                      <ItemPicker items={items} usual={usual} value={line.item} onChange={(id) => pickItem(i, id)} />
                      <Input aria-label="Quantity" type="number" min={1} value={line.qty} onChange={(e) => entry.update(i, { qty: e.target.value })} />
                      <Input aria-label="Unit cost" type="number" step="0.001" min={0} value={line.cost} onChange={(e) => entry.update(i, { cost: e.target.value })} />
                      <div className="flex gap-1">
                        <Select aria-label="Discount type" className="w-[4.5rem] px-2" value={line.discType} onChange={(e) => entry.update(i, { discType: e.target.value as DiscountType })}>
                          <option value="amount">Amt</option>
                          <option value="percent">%</option>
                        </Select>
                        <Input aria-label="Discount" type="number" step="0.001" min={0} value={line.disc} onChange={(e) => entry.update(i, { disc: e.target.value })} />
                      </div>
                      <output aria-label="Line total" className="flex h-10 items-center justify-end text-sm font-medium tabular-nums">
                        {line.cost !== '' && lineComplete(line) ? money(lineGross(line) - cut(line.discType, line.disc, lineGross(line))) : '-'}
                      </output>
                      <span className="flex h-10 items-center text-ok" aria-label={line.committed ? 'Line saved' : undefined}>{line.committed && <Check className="h-4 w-4" aria-hidden />}</span>
                      {entry.rows.length > 1 ? <Button variant="ghost" size="icon" aria-label="Remove line" onClick={() => entry.remove(i)}><Trash2 className="h-4 w-4" /></Button> : <span />}
                    </div>
                    {line.item && hints[line.item] && (() => {
                      const h = hints[line.item]
                      const options = [
                        h.fromSupplier && { label: `Last from ${supplierName}`, price: h.fromSupplier.price, date: h.fromSupplier.date },
                        h.last && (!h.fromSupplier || h.last.price !== h.fromSupplier.price) && { label: h.last.supplier ? `Last paid (${h.last.supplier})` : 'Last paid', price: h.last.price, date: h.last.date },
                        h.average != null && { label: 'Average', price: h.average, date: null },
                        h.start != null && { label: 'Starting price', price: h.start, date: null },
                      ].filter(Boolean) as { label: string; price: number; date: string | null }[]
                      return (
                        <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
                          Use price:
                          {options.map((o) => (
                            <button key={o.label} type="button" onClick={() => entry.update(i, { cost: String(o.price) })}
                              className={`rounded-full border px-2 py-0.5 ${Number(line.cost) === o.price ? 'border-brand bg-brand-soft text-brand-deep' : 'border-border hover:bg-surface-muted'}`}>
                              {o.label} {money(o.price)}{o.date ? ` (${fmtDate(o.date)})` : ''}
                            </button>
                          ))}
                        </p>
                      )
                    })()}
                    {docType === 'receipt' && line.item && Number(line.qty) > 0 && line.cost === '' && (
                      <p role="status" className="text-xs text-warn">No price entered: this stock will be valued at zero, which lowers the stock value and the average cost until a price is set.</p>
                    )}
                    {entry.incomplete === i && <p role="alert" className="text-xs text-danger">Choose an item and a quantity, then press Enter.</p>}
                  </div>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="outline" size="sm" onClick={entry.addRow}><Plus className="h-4 w-4" /> Add line</Button>
            </div>
          </div>

          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-3">
              <Field label="Invoice discount">
                <div className="flex gap-1">
                  <Select aria-label="Invoice discount type" className="w-24" value={docDiscType} onChange={(e) => setDocDiscType(e.target.value as DiscountType)}>
                    <option value="amount">Amount</option>
                    <option value="percent">Percent</option>
                  </Select>
                  <Input aria-label="Invoice discount" type="number" step="0.001" min={0} className="w-28" value={docDisc} onChange={(e) => setDocDisc(e.target.value)} />
                </div>
              </Field>
            </div>
            {hasCosts ? (
              <dl className="grid min-w-60 grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm" aria-label="Totals">
                <dt>Sub total</dt><dd className="text-right tabular-nums">{money(subtotal)}</dd>
                <dt>Line discounts</dt><dd className="text-right tabular-nums">-{money(lineDiscounts)}</dd>
                <dt>Invoice discount</dt><dd className="text-right tabular-nums">-{money(docDiscount)}</dd>
                <dt>Total discount</dt><dd className="text-right tabular-nums">-{money(lineDiscounts + docDiscount)}</dd>
                <dt className="border-t border-border pt-1 font-semibold">Total</dt><dd className="border-t border-border pt-1 text-right font-semibold tabular-nums">{money(total)}</dd>
              </dl>
            ) : <span className="text-sm text-ink-muted">No costs entered</span>}
          </div>
          <Button disabled={!supplierId || !locationId || !invoice.trim() || filled.length === 0 || new Set(filled.map((l) => l.item)).size !== filled.length || (correcting !== null && reason.trim().length < 5)} onClick={post}>
            {correcting ? 'Save the correction' : docType === 'receipt' ? 'Post receipt' : 'Post return'}
          </Button>
          {new Set(filled.map((l) => l.item)).size !== filled.length && <p className="text-sm text-danger">An item appears twice; combine the quantities into one line.</p>}
        </CardContent>
      </Card>

      <h2 className="text-lg font-semibold">Documents</h2>
      <div className="filter-bar">
        <Select aria-label="Supplier filter" className="w-auto" value={filterSupplier} onChange={(e) => { setFilterSupplier(e.target.value); setPage(1) }}>
          <option value="">All suppliers</option>
          {suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </Select>
        <Select aria-label="Status filter" className="w-auto" value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1) }}>
          <option value="">Posted and void</option>
          <option value="posted">Posted</option>
          <option value="void">Void</option>
        </Select>
        <Input aria-label="Search invoices" className="w-56" placeholder="Search invoice or note" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        <Select aria-label="Date filter basis" className="w-auto" value={dateBy} onChange={(e) => { setDateBy(e.target.value as typeof dateBy); setPage(1) }}>
          <option value="invoice">By invoice date</option>
          <option value="received">By received date</option>
        </Select>
        <Input aria-label="From date" type="date" className="w-auto" value={filterFrom} onChange={(e) => { setFilterFrom(e.target.value); setPage(1) }} />
        <Input aria-label="To date" type="date" className="w-auto" value={filterTo} onChange={(e) => { setFilterTo(e.target.value); setPage(1) }} />
      </div>
      <Table>
        <thead><tr><Th>#</Th><Th>Received</Th><Th>Type</Th><Th>Supplier</Th><Th>Invoice</Th><Th>Invoice date</Th><Th>Location</Th><Th className="text-right">Total</Th><Th>Status</Th><Th /></tr></thead>
        <tbody>
          {list.loading && !list.data ? <SkeletonRows cols={10} /> : list.data?.items.map((d) => (
            <tr key={d.id}>
              <Td>{d.id}</Td>
              <Td title={`Entered ${fmtDateTime(d.received_at)}`}>{fmtDate(d.received_on)}</Td>
              <Td><Badge tone={d.doc_type === 'receipt' ? 'ok' : 'warn'}>{LABEL[d.doc_type]}</Badge></Td>
              <Td className="font-medium">{d.supplier}</Td>
              <Td>{d.invoice_number}</Td>
              <Td>{d.invoice_date ? fmtDate(d.invoice_date) : '-'}</Td>
              <Td>{places.get(d.location_id)}</Td>
              <Td className="text-right tabular-nums">{d.total != null ? money(d.total) : '-'}</Td>
              <Td><StatusBadge status={d.status} /></Td>
              <Td><div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => open(d)}>View</Button>
                {canVoid && d.status === 'posted' && <Button size="sm" variant="outline" onClick={() => correct(d)}>Correct items</Button>}
                {canVoid && d.status === 'posted' && <Button size="sm" variant="outline" onClick={() => startEdit(d)}>Edit</Button>}
              </div></Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {list.data?.items.length === 0 && <EmptyState title="No receiving documents" />}
      {list.data && <Pagination page={page} size={SIZE} total={list.data.total} onPage={setPage} />}

      <Modal
        open={editing !== null}
        title={editing ? `Edit ${LABEL[editing.doc_type].toLowerCase()} #${editing.id}` : ''}
        description="Changes the invoice number, dates and note. Stock is not affected, and the change is recorded in the audit log."
        onClose={() => setEditing(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
          <Button type="submit" form="edit-doc-form" disabled={!edit.invoice.trim() || !edit.receivedOn}>Save changes</Button>
        </>}
      >
        <form id="edit-doc-form" onSubmit={saveEdit} className="grid gap-5 sm:grid-cols-2">
          <Field label="Invoice number"><Input required maxLength={60} value={edit.invoice} onChange={(e) => setEdit({ ...edit, invoice: e.target.value })} /></Field>
          <Field label="Received on"><Input required type="date" max={iso(new Date())} value={edit.receivedOn} onChange={(e) => setEdit({ ...edit, receivedOn: e.target.value })} /></Field>
          <Field label="Invoice date"><Input type="date" max={iso(new Date())} value={edit.invoiceDate} onChange={(e) => setEdit({ ...edit, invoiceDate: e.target.value })} /></Field>
          <Field label="Note"><Input maxLength={1000} value={edit.note} onChange={(e) => setEdit({ ...edit, note: e.target.value })} /></Field>
        </form>
      </Modal>

      <Modal open={detail !== null} title={detail ? `${LABEL[detail.doc_type]} #${detail.id}` : ''} onClose={() => { setDetail(null); setVoiding(false) }}>
        {detail && (
          <div className="space-y-3 text-sm">
            <p><strong>{detail.supplier}</strong> - invoice {detail.invoice_number}{detail.invoice_date && ` dated ${detail.invoice_date}`}</p>
            <p className="text-ink-muted">Received {fmtDate(detail.received_on)}. Entered {fmtDateTime(detail.received_at)} by {detail.received_by_name} at {places.get(detail.location_id)}</p>
            {detail.note && <p>{detail.note}</p>}
            <Table>
              <thead><tr><Th>Item</Th><Th className="text-right">Qty</Th><Th className="text-right">Unit cost</Th><Th className="text-right">Discount</Th><Th className="text-right">Line total</Th></tr></thead>
              <tbody>
                {detail.lines?.map((l) => (
                  <tr key={l.item_id}><Td>{l.code} - {l.name}</Td><Td className="text-right tabular-nums">{l.qty}</Td><Td className="text-right tabular-nums">{l.unit_cost != null ? money(l.unit_cost) : '-'}</Td><Td className="text-right tabular-nums">{l.discount_amount ? `-${money(l.discount_amount)}` : '-'}</Td><Td className="text-right tabular-nums">{l.line_total != null ? money(l.line_total) : '-'}</Td></tr>
                ))}
              </tbody>
            </Table>
            {detail.total != null && (
              <dl className="ml-auto grid w-60 grid-cols-[1fr_auto] gap-x-6 gap-y-1">
                <dt>Sub total</dt><dd className="text-right tabular-nums">{money(detail.subtotal ?? 0)}</dd>
                <dt>Line discounts</dt><dd className="text-right tabular-nums">-{money(detail.line_discount_total ?? 0)}</dd>
                <dt>Invoice discount{detail.discount_type === 'percent' ? ` (${detail.discount_value}%)` : ''}</dt><dd className="text-right tabular-nums">-{money(detail.discount_amount ?? 0)}</dd>
                <dt>Total discount</dt><dd className="text-right tabular-nums">-{money(detail.total_discount ?? 0)}</dd>
                <dt className="border-t border-border pt-1 font-semibold">Total</dt><dd className="border-t border-border pt-1 text-right font-semibold tabular-nums">{money(detail.total)}</dd>
              </dl>
            )}
            {detail.status === 'void' && <p className="rounded-md bg-surface-muted p-2">Voided: {detail.void_reason}</p>}
            {detail.status === 'posted' && canVoid && !voiding && (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => startCorrection(detail)}>Correct items and prices</Button>
                <Button variant="outline" onClick={() => startEdit(detail)}>Edit details</Button>
                <Button variant="danger" onClick={() => setVoiding(true)}>Void this document</Button>
              </div>
            )}
            {detail.status === 'posted' && canVoid && !voiding && <p className="text-xs text-ink-muted">Edit details changes the invoice number, dates and note. Correct items and prices opens the whole invoice to fix lines; the original is reversed and replaced.</p>}
            {voiding && (
              <div className="space-y-2 rounded-xl border border-danger/20 border-l-4 border-l-danger bg-danger-soft p-3">
                <p className="text-danger">Voiding reverses the stock with new ledger entries. The original entries stay in the history.</p>
                <Field label="Reason"><Input value={voidReason} onChange={(e) => setVoidReason(e.target.value)} /></Field>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setVoiding(false)}>Cancel</Button>
                  <Button variant="danger" disabled={voidReason.trim().length < 5} onClick={voidDoc}>Confirm void</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
