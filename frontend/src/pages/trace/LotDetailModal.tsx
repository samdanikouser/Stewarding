import { FileText } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { openPdf } from '@/lib/download'
import { useAuth } from '@/lib/auth'
import { fmtDate, fmtDateTime } from '@/lib/format'
import { useRun, useToast } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { LabelActions } from '@/pages/trace/LabelActions'
import { cn } from '@/lib/utils'
import { STATUS_LABEL, STATUS_TONE, type Lot, type Status, type TimelineItem, type Trace } from '@/pages/trace/types'

interface Props {
  initialId: number
  onClose: () => void
  onChanged: () => void
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt className="text-xs text-ink-muted">{label}</dt><dd className="text-sm font-medium">{children || '-'}</dd></div>
}

function Family({ title, lots, onOpen }: { title: string; lots: Lot[]; onOpen: (id: number) => void }) {
  if (lots.length === 0) return null
  return (
    <section className="space-y-1">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {lots.map((l) => (
          <li key={l.id}>
            <button type="button" className="flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-surface-muted" onClick={() => onOpen(l.id)}>
              <span><span className="font-medium">{l.code}</span> <span className="text-ink-muted">{l.item}{l.pack_description ? `, ${l.pack_count ?? ''} x ${l.pack_description}` : ''}</span></span>
              <Badge tone={STATUS_TONE[l.status]}>{STATUS_LABEL[l.status]}</Badge>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

const DOT = { neutral: 'bg-ink-muted', ok: 'bg-ok', critical: 'bg-danger' }

function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Timeline from the supplier to the plate</h3>
      <ol className="space-y-3 border-l-2 border-border pl-5">
        {items.map((item, n) => (
          <li key={n} className="relative">
            <span aria-hidden className={cn('absolute -left-[1.7rem] top-1.5 h-3 w-3 rounded-full ring-4 ring-surface', DOT[item.tone])} />
            <p className="text-sm"><span className="font-semibold">{item.title}</span> <span className="text-ink-muted">{item.lot_code}</span></p>
            <p className="text-sm text-ink-muted">{item.detail}</p>
            <p className="text-xs text-ink-muted">{fmtDateTime(item.at)}{item.by ? ` - ${item.by}` : ''}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}

/** One lot with where it came from, what was made from it, the checks that used it and its history; other lots open from the lists. */
export function LotDetailModal({ initialId, onClose, onChanged }: Props) {
  const { me } = useAuth()
  const run = useRun()
  const toast = useToast()
  const [id, setId] = useState(initialId)
  const [note, setNote] = useState('')
  const { data, reload } = useApi<Trace>(`/lots/${id}`)
  const can = (permission: string) => me?.permissions.includes(permission) ?? false
  const lot = data?.lot

  async function change(status: Status) {
    if (await run(() => api(`/lots/${id}/status`, { body: { status, note: note || null } }), 'Lot updated')) {
      setNote('')
      reload()
      onChanged()
    }
  }

  async function thaw() {
    if (await run(() => api(`/lots/${id}/thaw`, { method: 'POST', body: {} }), 'Lot thawed: reprint its label')) {
      reload()
      onChanged()
    }
  }

  async function exportTrace() {
    if (!(await openPdf(`/api/lots/${id}/trace/export`))) toast('error', 'Could not make the trace')
  }

  return (
    <Modal size="xl" open title={lot ? `Lot ${lot.code}` : 'Lot'} description={lot ? `${lot.item}, ${lot.location ?? ""}` : undefined} onClose={onClose}>
      {!lot || !data ? <Skeleton className="h-40 w-full" /> : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[lot.status]}>{STATUS_LABEL[lot.status]}</Badge>
            {lot.past_use_by && lot.status === 'active' && <Badge tone="critical">Past use-by</Badge>}
            <span className="text-lg font-semibold">{lot.item}</span>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
            <Fact label="Type">{lot.kind === 'portion' ? 'Portions' : 'Delivery'}</Fact>
            <Fact label="Storage">{lot.condition_label}{lot.thawed_at ? ` (thawed ${fmtDateTime(lot.thawed_at)})` : ''}</Fact>
            <Fact label="Supplier">{lot.supplier}</Fact>
            <Fact label="Supplier lot">{lot.supplier_lot}</Fact>
            <Fact label="Produced">{lot.produced_on ? fmtDate(lot.produced_on) : ''}</Fact>
            <Fact label="Expiry (supplier)">{lot.expiry_on ? fmtDate(lot.expiry_on) : ''}</Fact>
            <Fact label="Use by">{lot.use_by ? fmtDateTime(lot.use_by) : ''}</Fact>
            <Fact label={lot.kind === 'portion' ? 'Portioned' : 'Received'}>{`${fmtDateTime(lot.created_at)}${lot.created_by_name ? ` by ${lot.created_by_name}` : ''}`}</Fact>
            <Fact label="Temperature on arrival">{lot.temp_c != null ? `${lot.temp_c} C` : ''}</Fact>
            <Fact label="Quantity">{lot.qty != null ? `${lot.qty} ${lot.unit ?? ''}` : ''}</Fact>
            <Fact label="Waste">{lot.waste_qty ? `${lot.waste_qty} ${lot.unit ?? ''}` : ''}</Fact>
            <Fact label="Pack">{lot.pack_description ? `${lot.pack_count ?? ''} x ${lot.pack_description}` : ''}</Fact>
            <Fact label="Tag number">{lot.tag_number}</Fact>
            <Fact label="Location">{lot.location}</Fact>
            <Fact label="Note">{lot.note}</Fact>
          </dl>

          <div className="flex flex-wrap items-end justify-between gap-3 rounded-lg bg-surface-muted p-3">
            <LabelActions ids={[lot.id]} packs={lot.kind === 'portion' ? lot.pack_count ?? 0 : 0} />
            <Button type="button" variant="outline" onClick={exportTrace}><FileText className="h-4 w-4" aria-hidden /> Trace report (PDF)</Button>
          </div>

          {(can('lot.split') || can('lot.manage')) && (
            <div className="flex flex-wrap items-end gap-2">
              <Input aria-label="Reason" placeholder="Reason (needed to discard or hold)" className="max-w-xs" value={note} onChange={(e) => setNote(e.target.value)} />
              {can('lot.split') && lot.status === 'active' && lot.condition === 'frozen' && <Button type="button" onClick={thaw}>Thaw this lot</Button>}
              {lot.status === 'active' && <Button type="button" variant="outline" onClick={() => change('used_up')}>Mark used up</Button>}
              {lot.status === 'active' && <Button type="button" variant="outline" onClick={() => change('discarded')}>Discard</Button>}
              {can('lot.manage') && lot.status === 'active' && <Button type="button" variant="outline" onClick={() => change('on_hold')}>Put on hold</Button>}
              {can('lot.manage') && lot.status !== 'active' && <Button type="button" variant="outline" onClick={() => change('active')}>{lot.status === 'on_hold' ? 'Release' : 'Reopen'}</Button>}
            </div>
          )}

          <Timeline items={data.timeline} />
          <Family title="Came from (back toward the supplier)" lots={data.back} onOpen={setId} />
          <Family title="Made from this lot" lots={data.forward} onOpen={setId} />
        </div>
      )}
    </Modal>
  )
}
