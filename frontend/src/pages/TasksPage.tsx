import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Pagination } from '@/components/ui/pagination'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState, Skeleton, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDateTime, label } from '@/lib/format'
import { PushToggle } from '@/components/PushToggle'
import { useRun, useToast } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { notificationsChanged } from '@/lib/notificationEvents'

interface Note {
  id: number
  kind: string
  priority: string
  title: string
  body: string | null
  location_id: number | null
  link: string | null
  created_at: string
  read_at: string | null
  requires_ack: boolean
  acknowledged_at: string | null
  action_needed: boolean
}

interface PendingItem {
  category: string
  location: string
  urgency: string
  responsible: string
  description: string
  overdue_minutes: number
  link: string
}

interface Task {
  id: number
  description: string
  effective_status: string
  due_at: string | null
  local_date: string
}

const TABS = [['notifications', 'Notifications'], ['tasks', 'My tasks'], ['pending', 'Pending activities']] as const
const SIZE = 15

function Notifications() {
  const { me } = useAuth()
  const run = useRun()
  const toast = useToast()
  const [unread, setUnread] = useState(false)
  const [page, setPage] = useState(1)
  const { data, loading, reload } = useApi<{ total: number; unread: number; items: Note[] }>(
    `/notifications${qs({ unread, page, size: SIZE })}`,
  )
  const places = new Map(me?.locations.map((l) => [l.id, l.name]))
  const [selected, setSelected] = useState<number[]>([])
  const open = (data?.items ?? []).filter((n) => n.requires_ack && !n.acknowledged_at)
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))

  async function acknowledgeMany(ids: number[]) {
    const result = await api<{ acknowledged: number }>('/notifications/acknowledge-many', { body: { ids } }).catch(() => null)
    if (result) {
      toast('ok', `${result.acknowledged} alert${result.acknowledged === 1 ? '' : 's'} acknowledged`)
      setSelected([])
      reload()
      notificationsChanged()
    } else toast('error', 'Could not acknowledge the alerts')
  }

  async function act(path: string, success?: string) {
    if (await run(() => api(`/notifications/${path}`, { method: 'POST' }), success)) {
      reload()
      notificationsChanged()
    }
  }

  return (
    <div className="space-y-3">
      <PushToggle />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={unread} onChange={(e) => { setUnread(e.target.checked); setPage(1) }} /> Unread only</label>
        <Button variant="outline" size="sm" onClick={() => act('read-all', 'All marked as read')}>Mark all as read ({data?.unread ?? 0})</Button>
      </div>
      {open.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface px-3 py-2 text-sm">
          <span>{open.length} alert{open.length === 1 ? '' : 's'} on this page need acknowledging</span>
          <Button size="sm" variant="outline" onClick={() => setSelected(open.map((n) => n.id))}>Select all</Button>
          <Button size="sm" disabled={selected.length === 0} onClick={() => acknowledgeMany(selected)}>Acknowledge selected ({selected.length})</Button>
        </div>
      )}
      {loading && !data ? <Skeleton className="h-32 w-full" /> : data?.items.length === 0 ? <EmptyState title="No notifications" /> : (
        <ul className="space-y-2">
          {data?.items.map((n) => (
            <li key={n.id} className={cn('rounded-lg border bg-surface p-4 text-sm',
              n.action_needed ? 'border-danger/60 bg-danger-soft' : n.priority === 'high' ? 'border-warn/50' : 'border-border')}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className={cn('flex items-center gap-2', !n.read_at && 'font-semibold')}>
                  {n.requires_ack && !n.acknowledged_at && <input type="checkbox" aria-label={`Select ${n.title}`} checked={selected.includes(n.id)} onChange={() => toggle(n.id)} />}
                  {n.title}
                </p>
                <div className="flex items-center gap-1">
                  {n.priority !== 'normal' && <Badge tone={n.priority === 'critical' ? 'critical' : 'warn'}>{n.priority}</Badge>}
                  {n.action_needed && <Badge tone="critical">Action needed</Badge>}
                </div>
              </div>
              {n.body && <p className="mt-1 text-ink-muted">{n.body}</p>}
              <p className="mt-1 text-xs text-ink-muted">{fmtDateTime(n.created_at)}{n.location_id && ` - ${places.get(n.location_id) ?? ''}`}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {n.link && <Button asChild size="sm" variant="outline"><Link to={n.link}>Open</Link></Button>}
                {!n.read_at && <Button size="sm" variant="ghost" onClick={() => act(`${n.id}/read`)}>Mark read</Button>}
                {n.requires_ack && !n.acknowledged_at && <Button size="sm" onClick={() => act(`${n.id}/acknowledge`, 'Acknowledged')}>Acknowledge</Button>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {data && <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />}
    </div>
  )
}

function MyTasks() {
  const { data, loading } = useApi<{ items: Task[] }>('/checklists/instances?mine=true&size=100')
  const open = (data?.items ?? []).filter((t) => !['completed', 'verified', 'waived', 'pending_verification'].includes(t.effective_status))
  if (loading && !data) return <Skeleton className="h-32 w-full" />
  if (open.length === 0) return <EmptyState title="No tasks assigned to you" />
  return (
    <ul className="space-y-2">
      {open.map((t) => (
        <li key={t.id}>
          <Link to="/checklists" className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface p-4 text-sm">
            <span><span className="block font-medium">{t.description}</span><span className="text-xs text-ink-muted">Due {fmtDateTime(t.due_at)}</span></span>
            <StatusBadge status={t.effective_status} />
          </Link>
        </li>
      ))}
    </ul>
  )
}

function Pending() {
  const { data, loading } = useApi<{ total: number; by_urgency: Record<string, number>; by_location: Record<string, Record<string, number>>; items: PendingItem[] }>('/notifications/pending-summary')
  if (loading && !data) return <Skeleton className="h-32 w-full" />
  if (!data || data.total === 0) return <EmptyState title="Nothing is pending" />
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 text-sm">
        <Badge tone="critical">{data.by_urgency.critical} critical</Badge>
        <Badge tone="warn">{data.by_urgency.high} high</Badge>
        <Badge>{data.by_urgency.normal} normal</Badge>
        {Object.entries(data.by_location).map(([loc, c]) => <Badge key={loc}>{loc}: {c.critical + c.high + c.normal}</Badge>)}
      </div>
      <Table>
        <thead><tr><Th>Urgency</Th><Th>Location</Th><Th>Activity</Th><Th>Responsible</Th><Th className="text-right">Overdue</Th></tr></thead>
        <tbody>
          {data.items.map((i, n) => (
            <tr key={n}>
              <Td><Badge tone={i.urgency === 'critical' ? 'critical' : i.urgency === 'high' ? 'warn' : 'neutral'}>{i.urgency}</Badge></Td>
              <Td>{i.location}</Td>
              <Td><Link className="hover:underline" to={i.link}>{i.description}</Link><span className="ml-2 text-xs text-ink-muted">{label(i.category)}</span></Td>
              <Td>{i.responsible}</Td>
              <Td className="text-right tabular-nums">{i.overdue_minutes ? `${i.overdue_minutes} min` : '-'}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  )
}

export function TasksPage() {
  const { me } = useAuth()
  const canSummary = me?.permissions.includes('report.view') ?? false
  const tabs = TABS.filter(([key]) => key !== 'pending' || canSummary)
  const [tab, setTab] = useState<(typeof TABS)[number][0]>('notifications')
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Tasks &amp; Notifications</h1>
      <div role="tablist" className="flex flex-wrap gap-2">
        {tabs.map(([key, text]) => (
          <Button key={key} role="tab" aria-selected={tab === key} size="sm" variant={tab === key ? 'default' : 'outline'} onClick={() => setTab(key)}>{text}</Button>
        ))}
      </div>
      {tab === 'notifications' && <Notifications />}
      {tab === 'tasks' && <MyTasks />}
      {tab === 'pending' && canSummary && <Pending />}
    </div>
  )
}
