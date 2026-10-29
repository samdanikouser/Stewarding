import { useState } from 'react'
import { LocationSelect } from '@/components/LocationSelect'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState, Skeleton, SkeletonRows, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDateTime, label } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { useAllItems } from '@/lib/useItems'
import { BreakageReportForm } from '@/pages/BreakageReportForm'
import { useMoney } from '@/lib/money'

interface Incident {
  id: number
  code: string
  occurred_at: string
  location_id: number
  item_id: number
  qty: number
  incident_type: string
  reason: string | null
  status: string
  est_cost: number | null
  reported_by: number
  reported_by_name?: string
}

type Dialog = { kind: 'review' | 'reject' | 'approve'; incident: Incident } | null
const SIZE = 15

export function BreakagePage() {
  const money = useMoney()
  const { me } = useAuth()
  const run = useRun()
  const can = (p: string) => me?.permissions.includes(p) ?? false
  const canList = can('breakage.view')
  const [locationId, setLocationId] = useState<number | null>(null)
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const [page, setPage] = useState(1)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [qty, setQty] = useState('')
  const [text, setText] = useState('')
  const { byId } = useAllItems()
  const places = new Map(me?.locations.map((l) => [l.id, l.name]))

  const list = useApi<{ total: number; items: Incident[]; totals: { cost: number; units: number } }>(canList
    ? `/breakage${qs({ location_id: locationId, incident_status: status, incident_type: type, page, size: SIZE })}` : null)
  const mine = useApi<Incident[]>(canList ? null : '/breakage/mine')
  const rows = canList ? list.data?.items : mine.data
  const reload = () => (canList ? list.reload() : mine.reload())

  async function send(path: string, body: unknown, success: string) {
    if (!dialog) return
    const ok = await run(() => api(`/breakage/${dialog.incident.id}/${path}`, { body }), success)
    if (ok) {
      setDialog(null)
      setText('')
      reload()
    }
  }

  const open = (kind: 'review' | 'reject' | 'approve', incident: Incident) => {
    setDialog({ kind, incident })
    setQty(String(incident.qty))
    setText('')
  }


  const rowActions = (i: Incident) => {
    if (i.reported_by === me?.id) return null
    if (i.status === 'reported' && can('breakage.review')) {
      return (
        <>
          <Button size="sm" onClick={() => open('review', i)}>Review</Button>
          <Button size="sm" variant="outline" onClick={() => open('reject', i)}>Reject</Button>
        </>
      )
    }
    if (i.status === 'pending_approval' && can('breakage.approve')) {
      return (
        <>
          <Button size="sm" onClick={() => open('approve', i)}>Approve</Button>
          <Button size="sm" variant="outline" onClick={() => open('reject', i)}>Reject</Button>
        </>
      )
    }
    return null
  }
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Breakage &amp; Damage Logs</h1>
      <Card>
        <CardHeader><CardTitle>Report an incident</CardTitle></CardHeader>
        <CardContent><BreakageReportForm onSaved={reload} /></CardContent>
      </Card>

      <h2 className="text-lg font-semibold">{canList ? 'Incidents' : 'My reports'}</h2>
      {canList && (
        <div className="filter-bar">
          <LocationSelect allowAll value={locationId} onChange={(id) => { setLocationId(id); setPage(1) }} />
          <Select aria-label="Status" className="w-auto" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
            <option value="">Any status</option>
            {['reported', 'pending_approval', 'approved', 'rejected'].map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </Select>
          <Select aria-label="Type" className="w-auto" value={type} onChange={(e) => { setType(e.target.value); setPage(1) }}>
            <option value="">Any type</option>
            {['breakage', 'damage', 'missing', 'written_off'].map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </Select>
        </div>
      )}
      <ul className="space-y-2 xl:hidden">
        {!rows ? <li><Skeleton className="h-24 w-full" /></li> : rows.map((i) => {
          const actions = canList ? rowActions(i) : null
          return (
            <li key={i.id} className="space-y-2 rounded-xl border border-border bg-surface p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{i.code}</span>
                <StatusBadge status={i.status} />
              </div>
              <p className="text-sm">
                {byId.get(i.item_id)?.name ?? i.item_id} <span className="text-ink-muted">x {i.qty}{i.est_cost != null ? ` - ${money(i.est_cost)}` : ''}</span>
              </p>
              <p className="text-xs text-ink-muted">{label(i.incident_type)} - {places.get(i.location_id)} - {fmtDateTime(i.occurred_at)}</p>
              {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
            </li>
          )
        })}
      </ul>
      <div className="hidden xl:block">
      <Table>
        <thead><tr><Th>Incident</Th><Th>When</Th><Th>Location</Th><Th>Item</Th><Th className="text-right">Qty</Th><Th className="text-right">Value</Th><Th>Type</Th><Th>Status</Th>{canList && <Th />}</tr></thead>
        <tbody>
          {!rows ? <SkeletonRows cols={9} /> : rows.map((i) => (
            <tr key={i.id}>
              <Td className="font-medium">{i.code}</Td>
              <Td>{fmtDateTime(i.occurred_at)}</Td>
              <Td>{places.get(i.location_id)}</Td>
              <Td>{byId.get(i.item_id)?.name ?? i.item_id}</Td>
              <Td className="text-right tabular-nums">{i.qty}</Td>
              <Td className="text-right tabular-nums">{i.est_cost != null ? money(i.est_cost) : '-'}</Td>
              <Td>{label(i.incident_type)}</Td>
              <Td><StatusBadge status={i.status} /></Td>
              {canList && (
                <Td><div className="flex items-center justify-end gap-2 whitespace-nowrap">{rowActions(i)}</div></Td>
              )}
            </tr>
          ))}
        </tbody>
      </Table>
      </div>
      {rows?.length === 0 && <EmptyState title="No incidents" />}
      {canList && list.data && list.data.total > 0 && (
        <p role="status" className="text-right text-sm">
          Total breakage value for this selection <span className="ml-2 text-base font-semibold tabular-nums">{money(list.data.totals.cost)}</span>
          <span className="ml-2 text-ink-muted">({list.data.totals.units} units, rejected excluded)</span>
        </p>
      )}
      {canList && list.data && <Pagination page={page} size={SIZE} total={list.data.total} onPage={setPage} />}

      <Modal open={dialog !== null} title={dialog ? `${label(dialog.kind)} ${dialog.incident.code}` : ''} onClose={() => setDialog(null)}>
        {dialog && (
          <div className="space-y-3">
            {dialog.kind === 'review' && (
              <>
                <p className="text-sm text-ink-muted">Confirm the quantity. Stock is deducted once the incident is approved; larger incidents go to a manager first.</p>
                <Field label="Confirmed quantity"><Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
                <Field label="Preventive action (optional)"><Input value={text} onChange={(e) => setText(e.target.value)} /></Field>
              </>
            )}
            {dialog.kind === 'approve' && <Field label="Note (optional)"><Input value={text} onChange={(e) => setText(e.target.value)} /></Field>}
            {dialog.kind === 'reject' && <Field label="Reason for rejecting"><Input value={text} onChange={(e) => setText(e.target.value)} /></Field>}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDialog(null)}>Cancel</Button>
              {dialog.kind === 'review' && <Button onClick={() => send('review', { qty: Number(qty), preventive_action: text || null }, 'Incident reviewed')}>Confirm review</Button>}
              {dialog.kind === 'approve' && <Button onClick={() => send('approve', { note: text || null }, 'Incident approved and stock adjusted')}>Approve</Button>}
              {dialog.kind === 'reject' && <Button variant="danger" disabled={text.trim().length < 5} onClick={() => send('reject', { reason: text }, 'Incident rejected')}>Reject</Button>}
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
