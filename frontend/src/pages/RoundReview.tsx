import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { EmptyState, Skeleton, Table, Td, Th } from '@/components/ui/table'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { api, tokenStore } from '@/lib/api'
import { useMoney } from '@/lib/money'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface Item {
  item_id: number
  code: string
  name: string
  category: string | null
  received: number
  book: number
  counted: number
  by_location: Record<string, number>
  locations: { location: string; opening: number; counted: number; difference: number }[]
  unaccounted: number
  value: number
  within_tolerance: boolean
  not_counted?: boolean
  tolerance: number
  reasons: string[]
  state: 'balanced' | 'within_tolerance' | 'needs_review' | 'not_counted' | 'approved' | 'recount'
}

interface Review {
  round: { id: number; name: string; status: string; baseline: boolean; locations: { status: string; location: string }[] }
  first_round: boolean
  rows: Item[]
  states: Record<string, number>
  shortage_value: number
  surplus_value: number
}

const STATE: Record<Item['state'], { text: string; tone: 'ok' | 'warn' | 'critical' | 'neutral' }> = {
  balanced: { text: 'Balanced', tone: 'ok' },
  within_tolerance: { text: 'Within tolerance', tone: 'neutral' },
  needs_review: { text: 'Needs review', tone: 'warn' },
  not_counted: { text: 'Not counted anywhere', tone: 'critical' },
  approved: { text: 'Approved', tone: 'ok' },
  recount: { text: 'Recount', tone: 'critical' },
}

const PAGE = 60

/** The manager's view of a round: every item's unaccounted stock, approve what is acceptable, send the rest back, then post. */
export function RoundReview({ roundId, canManage, posted = false, onChanged }: { roundId: number; canManage: boolean; posted?: boolean; onChanged: () => void }) {
  const money = useMoney()
  const run = useRun()
  const { data, reload } = useApi<Review>(`/rounds/${roundId}/review`)
  const [show, setShow] = useState(posted ? 'approved' : 'open')
  const [shown, setShown] = useState(PAGE)
  const [posting, setPosting] = useState(false)
  const [gap, setGap] = useState<'start' | 'usage' | null>(null)  // the first round only: how to treat the gap

  if (!data) return <Skeleton className="h-48 w-full" />
  const open = data.round.status === 'counting'
  const allDone = data.round.locations.every((l) => l.status === 'done')
  const filters: Record<string, (r: Item) => boolean> = {
    open: (r) => r.state === 'needs_review' || r.state === 'not_counted' || r.state === 'within_tolerance' || r.state === 'recount',
    all: () => true,
  }
  const rows = data.rows.filter(filters[show] ?? ((r) => r.state === show))
  const toApprove = data.rows.filter((r) => r.state !== 'balanced' && r.state !== 'approved')
  const inTolerance = data.rows.filter((r) => r.state === 'within_tolerance').length
  const blocked = data.rows.filter((r) => r.state === 'recount').length

  async function act(path: string, body: unknown, message: string) {
    if (await run(() => api(`/rounds/${roundId}/${path}`, { body }), message)) {
      reload()
      onChanged()
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {([['needs_review', 'Needs review', data.states.needs_review ?? 0], ['not_counted', 'Not counted anywhere', data.states.not_counted ?? 0], ['within_tolerance', 'Within tolerance', inTolerance], ['approved', 'Approved', data.states.approved ?? 0], ['recount', 'Recount', blocked]] as const).map(([key, label, n]) => (
          <button key={key} type="button" aria-pressed={show === key} title={`Show only: ${label}`} onClick={() => { setShow(key); setShown(PAGE) }}
            className={`rounded-xl text-left outline-offset-2 ${show === key ? 'ring-2 ring-brand' : ''}`}>
            <Card><CardContent className="py-3"><p className="text-xs text-ink-muted">{label}</p><p className="text-2xl font-semibold tabular-nums">{n}</p></CardContent></Card>
          </button>
        ))}
      </div>
      <p className="text-sm text-ink-muted">
        {posted ? 'This round is posted. Unaccounted stock below is what left as usage when it was posted.' : 'Unaccounted stock is what the books hold minus what was counted in all locations.'} Shortage value {money(data.shortage_value)}
        {data.surplus_value > 0 && `, surplus value ${money(data.surplus_value)}`}.
        {data.round.baseline && ' This is a baseline round: the gap is taken as the starting point and is not charged to cost.'}
      </p>
      {open && data.first_round && canManage && (
        <fieldset className="space-y-2 rounded-lg border border-border bg-surface-muted/50 p-3 text-sm">
          <legend className="px-1 font-medium">This is your first count: how should the gap be treated?</legend>
          <p className="text-ink-muted">The books say {money(data.shortage_value)} more stock than was found. Most of that is likely stock used or lost before anything was tracked here.</p>
          <label className="flex items-start gap-2"><input type="radio" name="gap" className="mt-1" checked={gap === 'start'} onChange={() => setGap('start')} />
            <span><span className="font-medium">Accept it as the starting point.</span> Nothing is charged to cost. Opening stock stays as it was and the gap shows on its own "Baseline" line.</span></label>
          <label className="flex items-start gap-2"><input type="radio" name="gap" className="mt-1" checked={gap === 'usage'} onChange={() => setGap('usage')} />
            <span><span className="font-medium">Charge it as usage.</span> The Costs tab shows it as cost consumed for this period.</span></label>
        </fieldset>
      )}
      {!allDone && open && <p role="status" className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">Some locations are still counting. Numbers below are not final until all are done.</p>}

      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label="Show" className="w-auto" value={show} onChange={(e) => { setShow(e.target.value); setShown(PAGE) }}>
          <option value="open">To look at</option><option value="all">Everything</option>
          <option value="needs_review">Needs review</option><option value="not_counted">Not counted anywhere</option><option value="within_tolerance">Within tolerance</option>
          <option value="recount">Recount</option><option value="approved">Approved</option><option value="balanced">Balanced</option>
        </Select>
        {canManage && open && (
          <>
            <Button variant="outline" disabled={inTolerance === 0} onClick={() => act('approve', { within_tolerance: true }, 'Approved everything within tolerance')}>Approve all within tolerance ({inTolerance})</Button>
            <Button disabled={!allDone || blocked > 0 || toApprove.length > 0 || (data.first_round && gap === null)} title={toApprove.length ? 'Approve or recount every item with unaccounted stock first' : data.first_round && gap === null ? 'Choose how to treat the gap first' : undefined} onClick={() => setPosting(true)}>Post the round</Button>
          </>
        )}
        <Button variant="outline" asChild><a href={`/api/rounds/${roundId}/report.csv`} onClick={async (e) => {
          e.preventDefault()
          const blob = await fetch(`/api/rounds/${roundId}/report.csv`, { headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}` } }).then((r) => r.blob()).catch(() => null)
          if (blob) { const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `count-round-${roundId}.csv`; a.click(); URL.revokeObjectURL(url) }
        }}>Download the results</a></Button>
      </div>

      {rows.length === 0 ? <EmptyState title="Nothing in this list" /> : (
        <Table>
          <thead><tr><Th>Item</Th><Th className="text-right">Received</Th><Th className="text-right">Books</Th><Th>By location: opening, counted</Th><Th className="text-right">Unaccounted</Th><Th>Status</Th>{canManage && open && <Th />}</tr></thead>
          <tbody>
            {rows.slice(0, shown).map((r) => (
              <tr key={r.item_id}>
                <Td><span className="font-medium">{r.code} - {r.name}</span>{r.reasons.length > 0 && <span className="block text-xs text-ink-muted">Reason: {r.reasons.join('; ')}</span>}</Td>
                <Td className="text-right tabular-nums">{r.received}</Td>
                <Td className="text-right tabular-nums">{r.book}</Td>
                <Td className="text-xs">
                  <span className="font-semibold tabular-nums">Counted {r.counted} of {r.book}</span>
                  {r.locations.map((l) => (
                    <span key={l.location} className="block tabular-nums">{l.location}: {l.opening} to {l.counted}
                      <span className={l.difference < 0 ? 'text-warn' : l.difference > 0 ? 'text-danger' : 'text-ink-muted'}> ({l.difference > 0 ? '+' : ''}{l.difference})</span></span>
                  ))}
                </Td>
                <Td className="text-right tabular-nums"><span className={r.unaccounted > 0 ? 'text-warn' : r.unaccounted < 0 ? 'text-danger' : undefined}>{r.unaccounted > 0 ? '-' : r.unaccounted < 0 ? '+' : ''}{Math.abs(r.unaccounted)}</span>
                  {r.unaccounted !== 0 && <span className="block text-xs text-ink-muted">{money(Math.abs(r.value))}</span>}</Td>
                <Td><Badge tone={STATE[r.state].tone}>{STATE[r.state].text}</Badge></Td>
                {canManage && open && (
                  <Td>
                    {r.unaccounted !== 0 && (
                      <div className="flex gap-1.5">
                        <Button size="sm" variant="outline" disabled={r.state === 'approved'} onClick={() => act('approve', { item_ids: [r.item_id] }, `${r.name} approved`)}>Approve</Button>
                        <Button size="sm" variant="outline" disabled={r.state === 'recount'} onClick={() => act('recount', { item_ids: [r.item_id], note: 'Count it again' }, `${r.name} sent back for a recount`)}>Recount</Button>
                      </div>
                    )}
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {rows.length > shown && <Button variant="outline" onClick={() => setShown((n) => n + PAGE)}>Show more ({rows.length - shown} left)</Button>}

      <ConfirmDialog open={posting} title="Post this round?" confirmLabel="Post the round" onCancel={() => setPosting(false)}
        message={`Stock in every location will be set to what was counted. ${data.first_round && gap === 'start' ? 'The gap is taken as the starting point and is not charged to cost.' : `The ${money(data.shortage_value)} unaccounted shortage becomes usage.`} This cannot be undone.`}
        onConfirm={async () => {
          setPosting(false)
          if (await run(() => api(`/rounds/${roundId}/post`, { body: data.first_round ? { baseline: gap === 'start' } : {} }), 'Round posted: stock now matches the counts')) { reload(); onChanged() }
        }} />
    </div>
  )
}
