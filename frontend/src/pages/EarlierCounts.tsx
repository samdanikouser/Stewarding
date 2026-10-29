import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { fmtDateTime } from '@/lib/format'
import { useApi } from '@/lib/useApi'
import { useAllItems } from '@/lib/useItems'

interface Count {
  id: number
  location_id: number
  counted_at: string
  status: string
  lines: { item_id: number; system_qty: number; counted_qty: number; variance: number; reason?: string | null }[]
}

/** Counts made one location at a time before count rounds: kept for the record, no longer started here. */
export function EarlierCounts() {
  const counts = useApi<Count[]>('/stock/counts')
  const places = new Map(useApi<{ id: number; name: string }[]>('/stock/locations').data?.map((l) => [l.id, l.name]))
  const { byId } = useAllItems()
  if (!counts.data) return <Skeleton className="h-24 w-full" />
  if (counts.data.length === 0) return null
  return (
    <section className="space-y-3" aria-label="Earlier counts">
      <h2 className="text-lg font-semibold">Earlier counts</h2>
      <p className="text-sm text-ink-muted">Counts made before count rounds, one location at a time. They stay in the history, the Item history and Reconciliation. New counts are done as a round.</p>
      {counts.data.map((c) => (
        <Card key={c.id}>
          <CardHeader className="pb-2">
            <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
              <span>Count #{c.id}: {places.get(c.location_id) ?? c.location_id}, {fmtDateTime(c.counted_at)}</span>
              <Badge tone={c.status === 'posted' ? 'ok' : 'neutral'}>{c.status === 'posted' ? 'Posted' : 'Not posted'}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-ink-muted">
            {c.lines.length === 0 ? <EmptyState title="No items" /> : (
              <ul>
                {c.lines.map((l) => (
                  <li key={l.item_id}>{byId.get(l.item_id)?.name ?? l.item_id}: system {l.system_qty}, counted {l.counted_qty}{l.variance !== 0 && <strong className="text-danger"> (variance {l.variance})</strong>}{l.reason && <span>. {l.reason}</span>}</li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      ))}
    </section>
  )
}
