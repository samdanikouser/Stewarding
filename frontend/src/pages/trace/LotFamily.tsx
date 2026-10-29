import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { fmtDateTime } from '@/lib/format'
import { amountText } from '@/lib/units'
import { STATUS_LABEL, STATUS_TONE, type Lot } from '@/pages/trace/types'

const quantity = (lot: Lot) => (lot.qty === null ? null : amountText(lot.qty, lot.unit ?? ''))

function Facts({ lot }: { lot: Lot }) {
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-ink-muted">
      {lot.supplier && <span>{lot.supplier}{lot.supplier_lot ? `, batch ${lot.supplier_lot}` : ''}</span>}
      <span>Use by {lot.use_by ? fmtDateTime(lot.use_by) : '-'}</span>
      {lot.past_use_by && lot.status === 'active' && <Badge tone="critical">Past use-by</Badge>}
      <span>{lot.location}</span>
    </span>
  )
}

/** A sub-lot made from the lot above it, drawn under it with a line down the side; its own sub-lots follow the same way. */
function SubLot({ lot, onOpen }: { lot: Lot; onOpen: (id: number) => void }) {
  return (
    <li>
      <button type="button" onClick={() => onOpen(lot.id)} className="flex w-full flex-wrap items-start justify-between gap-2 rounded-lg px-3 py-2 text-left hover:bg-surface-muted">
        <span className="min-w-0 space-y-0.5">
          <span className="block break-all text-sm font-semibold">{lot.code}</span>
          <span className="block text-sm">
            {lot.pack_count ? <>{lot.pack_count} x {lot.pack_description}</> : lot.pack_description}
            {quantity(lot) && <span className="text-ink-muted"> = {quantity(lot)} in all</span>}
          </span>
          <Facts lot={lot} />
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge>{lot.condition_label}</Badge>
          <Badge tone={STATUS_TONE[lot.status]}>{STATUS_LABEL[lot.status]}</Badge>
        </span>
      </button>
      {lot.children && lot.children.length > 0 && (
        <ul className="ml-4 space-y-1 border-l-2 border-border pl-2">{lot.children.map((c) => <SubLot key={c.id} lot={c} onOpen={onOpen} />)}</ul>
      )}
    </li>
  )
}

/** One delivery with what was made from it: how much came in, how much went into portions or waste, and each sub-lot beneath. */
export function LotFamily({ lot, onOpen }: { lot: Lot; onOpen: (id: number) => void }) {
  const [open, setOpen] = useState(true)
  const kids = lot.children ?? []
  const b = lot.balance
  return (
    <Card className="overflow-hidden">
      <button type="button" onClick={() => onOpen(lot.id)} className="block w-full space-y-1 p-4 text-left hover:bg-surface-muted/60">
        <span className="flex flex-wrap items-center justify-between gap-2">
          <span className="break-all text-base font-semibold">{lot.code}</span>
          <span className="flex flex-wrap items-center gap-1.5">
            {lot.kind === 'portion' && <Badge>Portion lot</Badge>}
            <Badge tone={STATUS_TONE[lot.status]}>{STATUS_LABEL[lot.status]}</Badge>
          </span>
        </span>
        <span className="block text-sm">
          <span className="font-medium">{lot.item}</span>
          {lot.pack_description && <span className="text-ink-muted"> - {lot.pack_count} x {lot.pack_description}</span>}
          {quantity(lot) && <span className="text-ink-muted"> - {quantity(lot)} received</span>}
        </span>
        <Facts lot={lot} />
      </button>
      {b && (
        <dl className="grid grid-cols-2 gap-px border-t border-border bg-border text-center sm:grid-cols-4">
          {[['Received', amountText(b.qty, b.unit)], ['In portions', amountText(b.portioned, b.unit)], ['Waste', amountText(b.waste, b.unit)], ['Left to portion', amountText(b.left, b.unit)]].map(([label, value]) => (
            <div key={label} className="bg-surface px-3 py-2">
              <dt className="text-xs text-ink-muted">{label}</dt>
              <dd className={`text-sm font-semibold tabular-nums ${label === 'Left to portion' && b.left <= 0 ? 'text-danger' : ''}`}>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {kids.length > 0 && (
        <div className="border-t border-border">
          <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex min-h-11 w-full items-center gap-2 px-4 text-sm font-medium text-brand-deep hover:bg-surface-muted/60">
            {open ? <ChevronDown aria-hidden className="h-4 w-4" /> : <ChevronRight aria-hidden className="h-4 w-4" />}
            {kids.length} sub-lot{kids.length === 1 ? '' : 's'} made from {lot.code}
          </button>
          {open && <ul className="space-y-1 px-3 pb-3">{kids.map((c) => <SubLot key={c.id} lot={c} onOpen={onOpen} />)}</ul>}
        </div>
      )}
    </Card>
  )
}
