import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/ui/status-badge'
import { useAuth } from '@/lib/auth'
import { fmtTime } from '@/lib/format'
import { qs, useApi } from '@/lib/useApi'

interface Task { id: number; description: string; effective_status: string; due_at: string | null; local_date: string }
interface Check { equipment_id: number; equipment: string; schedule_id: number; slot_at: string; status: string }
interface Alert { id: number; title: string; priority: string; link: string | null; action_needed: boolean }

/** What is waiting at the place that was scanned: checklist tasks, monitoring checks and this person's unread alerts. */
export function ScanSummary({ locationId }: { locationId: number }) {
  const { me } = useAuth()
  const can = (permission: string) => me?.permissions.includes(permission) ?? false
  const tasks = useApi<{ items: Task[] }>(can('checklist.view') ? `/checklists/instances${qs({ location_id: locationId, size: 100 })}` : null).data
  const checks = useApi<Check[]>(can('temp.view') ? `/monitoring/due${qs({ location_id: locationId })}` : null).data
  const alerts = useApi<{ unread: number; items: Alert[] }>(can('notification.view') ? `/notifications${qs({ unread: true, size: 5 })}` : null).data

  const open = (tasks?.items ?? []).filter((t) => ['not_started', 'in_progress', 'overdue'].includes(t.effective_status))
    .sort((a, b) => (a.due_at ?? '').localeCompare(b.due_at ?? ''))
  const late = open.filter((t) => t.effective_status === 'overdue').length
  const waiting = (checks ?? []).filter((c) => c.status !== 'done')
  const overdueChecks = waiting.filter((c) => c.status === 'overdue').length

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2 text-center" aria-label="Summary">
        <Link to="/checklists" className="rounded-xl border border-border bg-surface px-2 py-3">
          <p className="text-2xl font-semibold tabular-nums">{open.length}</p><p className="text-xs text-ink-muted">tasks open{late ? `, ${late} overdue` : ''}</p>
        </Link>
        <Link to="/monitoring" className="rounded-xl border border-border bg-surface px-2 py-3">
          <p className="text-2xl font-semibold tabular-nums">{waiting.length}</p><p className="text-xs text-ink-muted">checks waiting{overdueChecks ? `, ${overdueChecks} overdue` : ''}</p>
        </Link>
        <Link to="/notifications" className="rounded-xl border border-border bg-surface px-2 py-3">
          <p className="text-2xl font-semibold tabular-nums">{alerts?.unread ?? 0}</p><p className="text-xs text-ink-muted">unread alerts</p>
        </Link>
      </div>

      {alerts && alerts.items.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">Alerts for you</CardTitle></CardHeader>
          <CardContent className="pt-0">
            <ul className="divide-y divide-border">
              {alerts.items.map((a) => (
                <li key={a.id}><Link to={a.link ?? '/notifications'} className="flex items-center justify-between gap-2 py-2.5 text-sm">
                  <span className="font-medium">{a.title}</span>{a.action_needed ? <Badge tone="critical">Action needed</Badge> : a.priority !== 'normal' && <Badge tone="warn">{a.priority}</Badge>}
                </Link></li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {open.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">Checklist tasks to do</CardTitle></CardHeader>
          <CardContent className="pt-0">
            <ul className="divide-y divide-border">
              {open.slice(0, 8).map((t) => (
                <li key={t.id}><Link to="/checklists" className="flex items-center justify-between gap-2 py-2.5 text-sm">
                  <span><span className="block font-medium">{t.description}</span><span className="text-xs text-ink-muted">Due {fmtTime(t.due_at)}</span></span>
                  <StatusBadge status={t.effective_status} />
                </Link></li>
              ))}
            </ul>
            {open.length > 8 && <Link to="/checklists" className="block pt-2 text-sm font-medium text-brand-deep hover:underline">And {open.length - 8} more</Link>}
          </CardContent>
        </Card>
      )}

      {waiting.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">Monitoring checks</CardTitle></CardHeader>
          <CardContent className="pt-0">
            <ul className="divide-y divide-border">
              {waiting.slice(0, 8).map((c) => (
                <li key={`${c.schedule_id}-${c.slot_at}`}><Link to="/monitoring" className="flex items-center justify-between gap-2 py-2.5 text-sm">
                  <span><span className="block font-medium">{c.equipment}</span><span className="text-xs text-ink-muted">{c.status === 'upcoming' ? 'Opens' : 'Due'} {fmtTime(c.slot_at)}</span></span>
                  <Badge tone={c.status === 'overdue' ? 'critical' : c.status === 'due' ? 'warn' : 'neutral'}>{c.status}</Badge>
                </Link></li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
