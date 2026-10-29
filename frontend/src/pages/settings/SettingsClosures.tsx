import { Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { iso } from '@/lib/dates'
import { fmtDate } from '@/lib/format'
import { useRun, useToast } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface Closure {
  id: number
  location: string
  start_date: string
  end_date: string
  reason: string
}

/** Days a location (or all of them) is closed: its checklist tasks and monitoring checks are not expected, and nothing alerts. */
export function SettingsClosures() {
  const { me } = useAuth()
  const run = useRun()
  const toast = useToast()
  const { data, reload } = useApi<Closure[]>('/closures')
  const [form, setForm] = useState({ location: '', start: iso(new Date()), end: iso(new Date()), reason: '' })
  const [removing, setRemoving] = useState<Closure | null>(null)

  async function add(event: FormEvent) {
    event.preventDefault()
    let waived = 0
    const ok = await run(async () => {
      const made = await api<{ tasks_waived: number }>('/closures', { body: { location_id: form.location ? Number(form.location) : null, start_date: form.start, end_date: form.end, reason: form.reason } })
      waived = made.tasks_waived
    }, 'Closed days saved')
    if (ok) {
      setForm({ ...form, reason: '' })
      reload()
      if (waived) toast('ok', `${waived} task(s) already on the list for those days were set aside as "closed"`)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Mark days as closed</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-ink-muted">On a closed day the location's checklist tasks and monitoring checks are not expected and no alerts or reminders are sent for them. Tasks already made for those days are set aside.</p>
          <form onSubmit={add} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Location">
              <Select value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })}>
                <option value="">All locations</option>
                {me?.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </Select>
            </Field>
            <Field label="From"><Input required type="date" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value, end: form.end < e.target.value ? e.target.value : form.end })} /></Field>
            <Field label="To"><Input required type="date" min={form.start} value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} /></Field>
            <Field label="Reason"><Input required minLength={2} maxLength={200} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
            <div className="sm:col-span-2 lg:col-span-4"><Button type="submit"><Plus className="h-4 w-4" /> Mark as closed</Button></div>
          </form>
        </CardContent>
      </Card>

      <h2 className="text-lg font-semibold">Closed days</h2>
      {!data ? <Skeleton className="h-24 w-full" /> : data.length === 0 ? <EmptyState title="No closed days" /> : (
        <ul className="divide-y divide-border rounded-xl border border-border bg-surface">
          {data.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
              <span><span className="font-medium">{c.location}</span>: {fmtDate(c.start_date)}{c.end_date !== c.start_date && ` to ${fmtDate(c.end_date)}`}<span className="block text-xs text-ink-muted">{c.reason}</span></span>
              <Button size="icon" variant="ghost" aria-label={`Remove the closure on ${fmtDate(c.start_date)}`} onClick={() => setRemoving(c)}><Trash2 className="h-4 w-4" /></Button>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog open={removing !== null} title="Remove this closure?" confirmLabel="Remove"
        message="Checks and tasks are expected again on those days. Tasks that were already set aside stay set aside."
        onCancel={() => setRemoving(null)}
        onConfirm={async () => {
          const target = removing
          setRemoving(null)
          if (target && await run(() => api(`/closures/${target.id}`, { method: 'DELETE' }), 'Closure removed')) reload()
        }} />
    </div>
  )
}
