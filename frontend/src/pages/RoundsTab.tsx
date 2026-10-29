import { Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDate, fmtDateTime } from '@/lib/format'
import { iso } from '@/lib/dates'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { EarlierCounts } from '@/pages/EarlierCounts'
import { RoundCountEntry } from '@/pages/RoundCountEntry'
import { RoundReview } from '@/pages/RoundReview'

interface Round {
  id: number
  name: string
  status: 'counting' | 'posted' | 'cancelled'
  baseline: boolean
  deadline: string | null
  created_at: string
  posted_at: string | null
  locations: { location_id: number; location: string; status: 'counting' | 'done'; counted_items: number; updated_at: string | null }[]
}

const STATUS = { counting: { text: 'Counting', tone: 'warn' }, posted: { text: 'Posted', tone: 'ok' }, cancelled: { text: 'Cancelled', tone: 'neutral' } } as const

/** A count of every location in one go, checked together as a pool and approved by a manager before stock is written to match. */
export function RoundsTab() {
  const { me } = useAuth()
  const run = useRun()
  const canManage = me?.permissions.includes('stock.approve') ?? false
  const rounds = useApi<Round[]>('/rounds')
  const [openId, setOpenId] = useState<number | null>(null)
  const [counting, setCounting] = useState<{ id: number; name: string } | null>(null)
  const [starting, setStarting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [form, setForm] = useState({ name: '', deadline: '' })

  const list = rounds.data ?? []
  const current = list.find((r) => r.id === openId) ?? list.find((r) => r.status === 'counting') ?? list[0] ?? null

  async function start(event: FormEvent) {
    event.preventDefault()
    const ok = await run(async () => {
      const made = await api<Round>('/rounds', { body: { name: form.name, deadline: form.deadline || null } })
      setOpenId(made.id)
    }, 'Count round started')
    if (ok) {
      setStarting(false)
      rounds.reload()
    }
  }

  if (counting && current) return <RoundCountEntry roundId={current.id} locationId={counting.id} locationName={counting.name} onBack={() => { setCounting(null); rounds.reload() }} />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Count rounds</h2>
          <p className="text-sm text-ink-muted">Count every location, including the store. The counts added together can never be more than the books hold: everything received, less breakage, write-offs and earlier counts.</p>
        </div>
        {canManage && !list.some((r) => r.status === 'counting') && (
          <Button onClick={() => { setForm({ name: `${new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric' }).format(new Date())} count`, deadline: '' }); setStarting(true) }}>
            <Plus className="h-4 w-4" /> Start a round
          </Button>
        )}
      </div>

      {starting && (
        <Card>
          <CardHeader><CardTitle>Start a count round</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={start} className="grid gap-4 sm:grid-cols-2">
              <Field label="Name"><Input required minLength={2} maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Finish counting by (optional)"><Input type="date" min={iso(new Date())} value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} /></Field>
              <div className="flex gap-2 sm:col-span-2">
                <Button type="submit">Start</Button>
                <Button type="button" variant="outline" onClick={() => setStarting(false)}>Cancel</Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {!rounds.data ? <Skeleton className="h-40 w-full" /> : list.length === 0 ? <EmptyState title="No count rounds yet" /> : (
        <>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Rounds">
            {list.slice(0, 8).map((r) => (
              <Button key={r.id} role="tab" aria-selected={current?.id === r.id} size="sm" variant={current?.id === r.id ? 'default' : 'outline'} onClick={() => setOpenId(r.id)}>{r.name}</Button>
            ))}
          </div>
          {current && (
            <>
              <Card>
                <CardContent className="space-y-3 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{current.name}</span>
                      <Badge tone={STATUS[current.status].tone}>{STATUS[current.status].text}</Badge>
                      {current.baseline && <Badge>Baseline</Badge>}
                      {current.deadline && <span className="text-xs text-ink-muted">Counting to finish by {fmtDate(current.deadline)}</span>}
                      {current.posted_at && <span className="text-xs text-ink-muted">Posted {fmtDateTime(current.posted_at)}</span>}
                    </div>
                    {canManage && current.status === 'counting' && <Button variant="outline" size="sm" onClick={() => setCancelling(true)}>Cancel this round</Button>}
                  </div>
                  <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {current.locations.map((l) => (
                      <li key={l.location_id} className="rounded-lg border border-border p-3 text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{l.location}</span>
                          <Badge tone={l.status === 'done' ? 'ok' : 'neutral'}>{l.status === 'done' ? 'Counted' : 'Counting'}</Badge>
                        </div>
                        <p className="mt-1 text-xs text-ink-muted">{l.counted_items} item(s) entered{l.updated_at ? `, last saved ${fmtDateTime(l.updated_at)}` : ''}</p>
                        {current.status === 'counting' && (
                          <Button size="sm" variant={l.status === 'done' ? 'outline' : 'default'} className="mt-2" onClick={() => setCounting({ id: l.location_id, name: l.location })}>
                            {l.status === 'done' ? 'View or reopen' : 'Count here'}
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
              <RoundReview key={`${current.id}-${current.status}`} roundId={current.id} canManage={canManage} posted={current.status === 'posted'} onChanged={rounds.reload} />
            </>
          )}
        </>
      )}

      <EarlierCounts />

      <ConfirmDialog open={cancelling} title="Cancel this round?" confirmLabel="Cancel the round" message="The counts entered so far are kept for reference, but nothing will be posted to stock." onCancel={() => setCancelling(false)}
        onConfirm={async () => {
          setCancelling(false)
          if (current && await run(() => api(`/rounds/${current.id}/cancel`, { body: {} }), 'Round cancelled')) rounds.reload()
        }} />
    </div>
  )
}
