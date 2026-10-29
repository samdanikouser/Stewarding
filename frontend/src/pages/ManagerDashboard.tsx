import { AlertTriangle, CalendarCheck, ClipboardCheck, ClipboardList, Clock, Coffee, HeartCrack, LogIn, Package, PackageMinus, Thermometer, TriangleAlert, UserX, Wrench } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { greeting, HeroCard } from '@/components/HeroCard'
import { LocationSelect } from '@/components/LocationSelect'
import { BarList, ColumnChart, TrendLine } from '@/components/charts'
import { KpiCard } from '@/components/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { useAuth } from '@/lib/auth'
import { label } from '@/lib/format'
import { qs, useApi } from '@/lib/useApi'

interface Compliance {
  numerator: number
  denominator: number
  percent: number | null
}

interface Dashboard {
  kpis: {
    scheduled_today: number
    checked_in: number
    not_checked_in: number
    absent: number
    on_duty: number
    daily_completion: Compliance
    weekly_completion: Compliance
    overdue_tasks: number
    awaiting_approval: { tasks: number; readings: number; breakage: number }
    monitoring_checks: { done: number; due: number }
    failed_checks: number
    equipment_attention: number
    inventory: { qty: number; value: number }
    off_today: number
    low_stock_items: number
    breakage_today: number
    breakage_month: number
  }
  charts: {
    task_trend: { date: string; percent: number | null; done: number; due: number }[]
    weekly_compliance: ({ location: string } & Compliance)[]
    monitoring_compliance: { equipment: string; location: string; due: number; done: number; failed: number; percent: number | null }[]
    breakage_trend: { month: string; incidents: number; qty: number }[]
    inventory_movement: { date: string; in: number; out: number }[]
    attendance_trend: { date: string; present: number; absent: number; late: number }[]
  }
  sections?: string[]
  approvals?: string[]
  supervisor?: {
    pending: { total: number; items: { category: string; location: string; urgency: string; responsible: string; description: string; overdue_minutes: number; link: string }[] }
    staff_today: { name: string; shift: string; status: string; late_minutes: number }[]
    stock_requests: number
    to_verify: number
    failed_readings_open: number
  }
}

const pct = (c: Compliance) => (c.percent === null ? 'n/a' : `${c.percent}%`)
const ratio = (c: Compliance) => `${c.numerator} of ${c.denominator} due`

function KpiGroup({ title, link, children }: { title: string; link: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">{title}</h2>
        <Link to={link} className="text-sm text-brand underline">Open</Link>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>
    </section>
  )
}

export function ManagerDashboard() {
  const { me } = useAuth()
  const [locationId, setLocationId] = useState<number | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [taskStatus, setTaskStatus] = useState('')

  const { data, loading, error } = useApi<Dashboard>(
    `/dashboard${qs({ location_id: locationId, date_from: from, date_to: to, employee_id: employeeId, equipment_id: equipmentId, task_status: taskStatus })}`,
  )
  const people = useApi<{ items: { id: number; full_name: string }[] }>(me?.permissions.includes('employee.view') ? '/employees?size=200&status=active' : null)
  const equipment = useApi<{ id: number; name: string }[]>(me?.permissions.includes('equipment.view') ? '/equipment' : null)

  const k = data?.kpis
  const show = (section: string) => data?.sections?.includes(section) ?? true
  const approves = (kind: string) => data?.approvals?.includes(kind) ?? true
  const urgent = k && (k.failed_checks > 0 || k.overdue_tasks > 0 || k.equipment_attention > 0)

  return (
    <div className="space-y-5">
      <HeroCard
        eyebrow={new Intl.DateTimeFormat('en-GB', { dateStyle: 'full' }).format(new Date())}
        title={`${greeting()}, ${(me?.employee?.name ?? '').split(' ')[0] || 'there'}`}
        chips={k ? [
          ...(show('people') ? [{ label: `${k.checked_in} of ${k.scheduled_today} checked in` }] : []),
          ...(show('checklists') ? [{ label: `Daily checklists ${pct(k.daily_completion)}` }] : []),
          ...(show('monitoring') ? [{ label: `${k.monitoring_checks.done} of ${k.monitoring_checks.due} checks recorded` }] : []),
          ...(k.failed_checks > 0 ? [{ label: `${k.failed_checks} failed check(s)`, urgent: true }] : []),
          ...(k.overdue_tasks > 0 ? [{ label: `${k.overdue_tasks} overdue task(s)`, urgent: true }] : []),
        ] : []}
      />

      <div className="filter-bar">
        <LocationSelect allowAll value={locationId} onChange={setLocationId} />
        <Input aria-label="From date" type="date" className="w-auto" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Input aria-label="To date" type="date" className="w-auto" value={to} onChange={(e) => setTo(e.target.value)} />
        {show('people') && (
          <Select aria-label="Employee" className="w-auto" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">All employees</option>
            {people.data?.items.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </Select>
        )}
        {equipment.data && (
          <Select aria-label="Equipment" className="w-auto" value={equipmentId} onChange={(e) => setEquipmentId(e.target.value)}>
            <option value="">All equipment</option>
            {equipment.data.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </Select>
        )}
        {show('checklists') && (
          <Select aria-label="Task status" className="w-auto" value={taskStatus} onChange={(e) => setTaskStatus(e.target.value)}>
            <option value="">Any task status</option>
            {['completed', 'verified', 'pending_verification', 'overdue', 'failed', 'waived', 'upcoming'].map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </Select>
        )}
      </div>

      {error && <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}

      {urgent && k && (
        <div role="alert" className="rounded-xl border border-danger/20 border-l-4 border-l-danger bg-danger-soft px-4 py-3 text-sm text-danger">
          <p className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" aria-hidden /> Needs attention now</p>
          <ul className="mt-1 list-inside list-disc">
            {k.failed_checks > 0 && <li><Link className="underline" to="/monitoring">{k.failed_checks} failed check(s) today</Link></li>}
            {k.overdue_tasks > 0 && <li><Link className="underline" to="/checklists">{k.overdue_tasks} overdue task(s)</Link></li>}
            {k.equipment_attention > 0 && <li><Link className="underline" to="/equipment">{k.equipment_attention} monitoring point(s) need attention</Link></li>}
          </ul>
        </div>
      )}

      {loading && !data ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div> : k && (
        <div className="space-y-5">
          {k.awaiting_approval.tasks + k.awaiting_approval.readings + k.awaiting_approval.breakage > 0 && (
            <Link to="/tasks" className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-xl border border-warn/25 border-l-4 border-l-warn bg-warn-soft px-4 py-3 text-sm">
              <span className="font-semibold">Waiting for approval</span>
              {approves('tasks') && <span>{k.awaiting_approval.tasks} checklist task(s)</span>}
              {approves('readings') && <span>{k.awaiting_approval.readings} monitoring reading(s)</span>}
              {approves('breakage') && <span>{k.awaiting_approval.breakage} breakage report(s)</span>}
              <span className="ml-auto underline">Review</span>
            </Link>
          )}
          {(show('people')) && (
          <KpiGroup title="People today" link="/attendance">
            <KpiCard icon={CalendarCheck} label="Scheduled" value={k.scheduled_today} />
            <KpiCard icon={LogIn} label="Checked in" value={k.checked_in} tone="ok" />
            <KpiCard icon={UserX} label="Not checked in" value={k.not_checked_in} tone={k.absent ? 'warn' : 'default'} />
            <KpiCard icon={Coffee} label="Off today" value={k.off_today} />
          </KpiGroup>)}
          {(show('checklists')) && (
          <KpiGroup title="Checklists" link="/checklists">
            <KpiCard icon={ClipboardCheck} label="Daily completion" value={pct(k.daily_completion)} />
            <KpiCard icon={ClipboardList} label="Weekly completion" value={pct(k.weekly_completion)} />
            <KpiCard icon={Clock} label="Overdue tasks" value={k.overdue_tasks} tone={k.overdue_tasks ? 'critical' : 'default'} />
          </KpiGroup>)}
          {(show('monitoring')) && (
          <KpiGroup title="Food safety monitoring" link="/monitoring">
            <KpiCard icon={Thermometer} label="Checks recorded" value={`${k.monitoring_checks.done} / ${k.monitoring_checks.due}`} />
            <KpiCard icon={TriangleAlert} label="Failed checks" value={k.failed_checks} tone={k.failed_checks ? 'critical' : 'default'} />
            <KpiCard icon={Wrench} label="Points needing attention" value={k.equipment_attention} tone={k.equipment_attention ? 'warn' : 'default'} />
          </KpiGroup>)}
          {(show('stock') || show('breakage')) && (
          <KpiGroup title="Stock and breakage" link="/stock-movements">
            {show('stock') && <KpiCard icon={Package} label="Stock on hand" value={k.inventory.qty} />}
            {show('stock') && <KpiCard icon={PackageMinus} label="Low-stock items" value={k.low_stock_items} tone={k.low_stock_items ? 'warn' : 'default'} />}
            {show('breakage') && <KpiCard icon={HeartCrack} label="Breakage today" value={k.breakage_today} />}
          </KpiGroup>)}
        </div>
      )}

      {data && (
        <section aria-label="Charts" className="grid gap-4 lg:grid-cols-2">
          {show('checklists') && (
          <Card>
            <CardHeader><CardTitle>Daily task completion</CardTitle></CardHeader>
            <CardContent><TrendLine points={data.charts.task_trend.map((d) => ({ label: d.date, value: d.percent }))} /></CardContent>
          </Card>)}
          {show('checklists') && (
          <Card>
            <CardHeader><CardTitle>Weekly compliance by location</CardTitle></CardHeader>
            <CardContent><BarList items={data.charts.weekly_compliance.map((w) => ({ label: w.location, value: w.percent, sub: ratio(w) }))} /></CardContent>
          </Card>)}
          {show('monitoring') && (
          <Card>
            <CardHeader><CardTitle>Monitoring compliance by point</CardTitle></CardHeader>
            <CardContent>
              <BarList items={data.charts.monitoring_compliance.map((e) => ({ label: `${e.equipment} (${e.location})`, value: e.percent, sub: `${e.done} of ${e.due} checks, ${e.failed} failed` }))} />
            </CardContent>
          </Card>)}
          {show('breakage') && (
          <Card>
            <CardHeader><CardTitle>Monthly breakage</CardTitle></CardHeader>
            <CardContent><ColumnChart data={data.charts.breakage_trend} labelKey="month" series={[{ key: 'qty', label: 'Units', className: 'bg-danger' }, { key: 'incidents', label: 'Incidents', className: 'bg-warn' }]} /></CardContent>
          </Card>)}
          {show('stock') && (
          <Card>
            <CardHeader><CardTitle>Inventory movement</CardTitle></CardHeader>
            <CardContent><ColumnChart data={data.charts.inventory_movement} labelKey="date" series={[{ key: 'in', label: 'Received', className: 'bg-ok' }, { key: 'out', label: 'Used', className: 'bg-brand' }]} /></CardContent>
          </Card>)}
          {show('people') && (
          <Card>
            <CardHeader><CardTitle>Attendance and absenteeism</CardTitle></CardHeader>
            <CardContent><ColumnChart data={data.charts.attendance_trend} labelKey="date" series={[{ key: 'present', label: 'Present', className: 'bg-ok' }, { key: 'absent', label: 'Absent', className: 'bg-danger' }]} /></CardContent>
          </Card>)}
          </section>
      )}

      {data?.supervisor && (
        <section aria-label="Supervisor actions" className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Pending activities ({data.supervisor.pending.total})</CardTitle></CardHeader>
            <CardContent>
              {data.supervisor.pending.items.length === 0 ? <EmptyState title="Nothing outstanding" /> : (
                <ul className="divide-y divide-border text-sm">
                  {data.supervisor.pending.items.map((item, i) => (
                    <li key={i} className="flex items-start justify-between gap-2 py-2">
                      <Link to={item.link} className="min-w-0 hover:underline">
                        <span className="block truncate font-medium">{item.description}</span>
                        <span className="text-xs text-ink-muted">{item.location} - {item.responsible}{item.overdue_minutes > 0 && ` - ${item.overdue_minutes} min`}</span>
                      </Link>
                      <Badge tone={item.urgency === 'critical' ? 'critical' : item.urgency === 'high' ? 'warn' : 'neutral'}>{item.urgency}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Staff today</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2 text-sm">
                <Badge>{data.supervisor.to_verify} to verify</Badge>
                <Badge>{data.supervisor.failed_readings_open} open failed readings</Badge>
                <Badge>{data.supervisor.stock_requests} stock requests</Badge>
              </div>
              <ul className="divide-y divide-border text-sm">
                {data.supervisor.staff_today.map((s, i) => (
                  <li key={i} className="flex items-center justify-between py-2">
                    <span className="font-medium">{s.name}<span className="ml-2 text-ink-muted">{s.shift}</span></span>
                    <StatusBadge status={s.status} />
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </section>
      )}
    </div>
  )
}
