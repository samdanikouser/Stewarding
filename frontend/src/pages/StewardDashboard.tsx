import { AlertTriangle, ThermometerSun } from 'lucide-react'
import { Link } from 'react-router-dom'
import { greeting, HeroCard } from '@/components/HeroCard'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { useAuth } from '@/lib/auth'
import { fmtTime } from '@/lib/format'
import { useApi } from '@/lib/useApi'
import { MyShiftCard } from '@/pages/MyShiftCard'

interface StewardData {
  checked_in: boolean
  tasks: { total: number; done: number; overdue: number; outstanding: { id: number; description: string; status: string; due_at: string | null }[] }
  monitoring_checks: { due: number; overdue: number }
  unresolved_issues: number
}

export function StewardDashboard() {
  const { me } = useAuth()
  const { data, loading, reload } = useApi<StewardData>('/dashboard')
  const percent = data && data.tasks.total ? Math.round((data.tasks.done / data.tasks.total) * 100) : 0

  return (
    <div className="space-y-4">
      <HeroCard
        eyebrow={new Intl.DateTimeFormat('en-GB', { dateStyle: 'full' }).format(new Date())}
        title={`${greeting()}, ${(me?.employee?.name ?? '').split(' ')[0] || 'there'}`}
        chips={data ? [
          { label: `${data.tasks.done} of ${data.tasks.total} tasks done` },
          ...(data.tasks.overdue > 0 ? [{ label: `${data.tasks.overdue} overdue`, urgent: true }] : []),
          ...(data.monitoring_checks.due > 0 ? [{ label: `${data.monitoring_checks.due} checks due` }] : []),
        ] : []}
      />

      <MyShiftCard onChange={reload} />

      {loading && !data ? <Skeleton className="h-40 w-full" /> : data && (
        <>
          {(data.monitoring_checks.overdue > 0 || data.unresolved_issues > 0) && (
            <div role="alert" className="rounded-xl border border-danger/20 border-l-4 border-l-danger bg-danger-soft px-4 py-3 text-sm text-danger">
              <p className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" aria-hidden /> Safety checks need you</p>
              <ul className="mt-1 list-inside list-disc">
                {data.monitoring_checks.overdue > 0 && <li><Link className="underline" to="/monitoring">{data.monitoring_checks.overdue} check(s) overdue</Link></li>}
                {data.unresolved_issues > 0 && <li><Link className="underline" to="/monitoring">{data.unresolved_issues} failed check(s) still open</Link></li>}
              </ul>
            </div>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                Checklist progress
                <span className="text-sm font-normal text-ink-muted">{data.tasks.done} of {data.tasks.total} done</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="h-2 overflow-hidden rounded bg-border" role="img" aria-label={`${percent}% of tasks done`}>
                <div className="h-full bg-brand" style={{ width: `${percent}%` }} />
              </div>
              {data.tasks.outstanding.length === 0 ? <EmptyState title="All tasks are done" /> : (
                <ul className="divide-y divide-border">
                  {data.tasks.outstanding.map((t) => (
                    <li key={t.id}>
                      <Link to="/checklists" className="flex items-center justify-between gap-2 py-3 text-sm">
                        <span><span className="block font-medium">{t.description}</span><span className="text-xs text-ink-muted">Due {fmtTime(t.due_at)}</span></span>
                        <StatusBadge status={t.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Link to="/monitoring" className="block">
            <Card className={data.monitoring_checks.overdue ? 'border-danger/50' : undefined}>
              <CardContent className="flex items-center justify-between gap-3 py-4">
                <span className="flex items-center gap-2 font-medium"><ThermometerSun className="h-5 w-5 text-brand" aria-hidden /> Monitoring</span>
                <span className="flex gap-2">
                  <Badge tone={data.monitoring_checks.due ? 'warn' : 'neutral'}>{data.monitoring_checks.due} due</Badge>
                  <Badge tone={data.monitoring_checks.overdue ? 'critical' : 'neutral'}>{data.monitoring_checks.overdue} overdue</Badge>
                </span>
              </CardContent>
            </Card>
          </Link>
        </>
      )}
    </div>
  )
}
