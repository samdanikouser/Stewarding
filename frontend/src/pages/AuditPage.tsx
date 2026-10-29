import { ChevronDown, ChevronRight, Search, X } from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { EmptyState, SkeletonRows, Table, Td, Th } from '@/components/ui/table'
import { auditChanges, auditSummary } from '@/lib/auditDiff'
import { PRESETS, type Range } from '@/lib/dates'
import { fmtDateTime, initials, label } from '@/lib/format'
import { qs, useApi } from '@/lib/useApi'

interface Entry {
  id: number
  created_at: string
  user: string | null
  action: string
  entity: string
  entity_id: number | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

interface Options {
  entities: string[]
  actions: string[]
  users: { id: number; name: string }[]
}

const SIZE = 20
const QUICK = ['today', 'yesterday', 'week', 'month', 'last30']

const tone = (action: string) => {
  const verb = action.split('.').pop() ?? ''
  if (/delete|remove|deactivate|end|reject|void|cancel/.test(verb)) return 'critical' as const
  return /create|add|assign|upload|enroll/.test(verb) ? ('ok' as const) : ('neutral' as const)
}

export function AuditPage() {
  const [typed, setTyped] = useState('')
  const [search, setSearch] = useState('')
  const [user, setUser] = useState('')
  const [entity, setEntity] = useState('')
  const [action, setAction] = useState('')
  const [range, setRange] = useState<Range>(['', ''])
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<number[]>([])

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(typed)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [typed])

  const options = useApi<Options>('/audit/options')
  const { data, loading } = useApi<{ total: number; items: Entry[] }>(
    `/audit${qs({ search, user_id: user, entity, action, date_from: range[0], date_to: range[1], page, size: SIZE })}`,
  )
  const narrow = <T,>(set: (value: T) => void) => (value: T) => { set(value); setPage(1) }
  const activePreset = PRESETS.find((p) => range[0] !== '' && p.range()[0] === range[0] && p.range()[1] === range[1])?.key
  const userName = options.data?.users.find((u) => String(u.id) === user)?.name ?? ''

  const chips = [
    search && { text: `Search: ${search}`, clear: () => { setTyped(''); setSearch('') } },
    user && { text: `Person: ${userName || user}`, clear: () => narrow(setUser)('') },
    entity && { text: `Record: ${label(entity)}`, clear: () => narrow(setEntity)('') },
    action && { text: `Action: ${action}`, clear: () => narrow(setAction)('') },
    (range[0] || range[1]) && { text: `Dates: ${range[0] || 'start'} to ${range[1] || 'now'}`, clear: () => narrow(setRange)(['', '']) },
  ].flatMap((chip) => (chip ? [chip] : []))

  function clearAll() {
    setTyped('')
    setSearch('')
    setUser('')
    setEntity('')
    setAction('')
    setRange(['', ''])
    setPage(1)
  }

  const toggle = (id: number) => setOpen((ids) => (ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id]))

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-2xl font-semibold">Audit Logs</h1>
        {data && <p className="text-sm text-ink-muted">{data.total} {data.total === 1 ? 'entry' : 'entries'}</p>}
      </div>

      <section aria-label="Filters" className="space-y-4 rounded-xl border border-border bg-surface p-4 sm:p-5">
        <div className="relative">
          <Search aria-hidden className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink-muted" />
          <Input type="search" aria-label="Search the log" placeholder="Search by action, record type or record number" className="pl-9" value={typed} onChange={(e) => setTyped(e.target.value)} />
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Select aria-label="Person" value={user} onChange={(e) => narrow(setUser)(e.target.value)}>
            <option value="">Everyone</option>
            {options.data?.users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </Select>
          <Select aria-label="Record type" value={entity} onChange={(e) => narrow(setEntity)(e.target.value)}>
            <option value="">All record types</option>
            {options.data?.entities.map((name) => <option key={name} value={name}>{label(name)}</option>)}
          </Select>
          <Select aria-label="Action" value={action} onChange={(e) => narrow(setAction)(e.target.value)}>
            <option value="">All actions</option>
            {options.data?.actions.map((name) => <option key={name} value={name}>{name}</option>)}
          </Select>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
          <div className="flex items-center gap-2">
            <Input aria-label="From date" type="date" className="w-40" value={range[0]} max={range[1] || undefined} onChange={(e) => narrow(setRange)([e.target.value, range[1]])} />
            <span aria-hidden className="text-ink-muted">to</span>
            <Input aria-label="To date" type="date" className="w-40" value={range[1]} min={range[0] || undefined} onChange={(e) => narrow(setRange)([range[0], e.target.value])} />
          </div>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Quick date ranges">
            {PRESETS.filter((p) => QUICK.includes(p.key)).map((p) => (
              <Button key={p.key} size="sm" variant={activePreset === p.key ? 'default' : 'outline'} onClick={() => narrow(setRange)(p.range())}>{p.label}</Button>
            ))}
          </div>
        </div>

        {chips.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
            {chips.map((chip) => (
              <button key={chip.text} type="button" onClick={chip.clear} aria-label={`Remove filter ${chip.text}`}
                className="inline-flex items-center gap-1 rounded-full bg-brand-soft px-3 py-1 text-xs font-medium text-brand-deep hover:bg-brand-soft/70">
                {chip.text} <X aria-hidden className="h-3 w-3" />
              </button>
            ))}
            <Button size="sm" variant="ghost" onClick={clearAll}>Clear all</Button>
          </div>
        )}
      </section>

      <Table>
        <thead><tr><Th className="w-10" /><Th>Time</Th><Th>Person</Th><Th>Action</Th><Th>Record</Th><Th>What changed</Th></tr></thead>
        <tbody>
          {loading && !data ? <SkeletonRows cols={6} /> : data?.items.map((e) => {
            const changes = auditChanges(e.before, e.after)
            const expanded = open.includes(e.id)
            return (
              <Fragment key={e.id}>
                <tr>
                  <Td className="pr-0">
                    {changes.length > 0 && (
                      <button type="button" aria-expanded={expanded} aria-label={`${expanded ? 'Hide' : 'Show'} the changes in entry ${e.id}`} onClick={() => toggle(e.id)}
                        className="flex h-8 w-8 items-center justify-center rounded-md text-ink-muted hover:bg-surface-muted">
                        {expanded ? <ChevronDown className="h-4 w-4" aria-hidden /> : <ChevronRight className="h-4 w-4" aria-hidden />}
                      </button>
                    )}
                  </Td>
                  <Td className="whitespace-nowrap">{fmtDateTime(e.created_at)}</Td>
                  <Td>
                    <span className="flex items-center gap-2">
                      <span aria-hidden className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-muted text-[11px] font-semibold text-ink-muted">{e.user ? initials(e.user) : 'S'}</span>
                      {e.user ?? 'System'}
                    </span>
                  </Td>
                  <Td><Badge tone={tone(e.action)}>{e.action}</Badge></Td>
                  <Td className="whitespace-nowrap">{label(e.entity)}{e.entity_id ? ` #${e.entity_id}` : ''}</Td>
                  <Td className="max-w-md truncate text-ink-muted">{auditSummary(changes, e.before === null)}</Td>
                </tr>
                {expanded && (
                  <tr className="bg-surface-muted/50">
                    <Td colSpan={6} className="px-4 py-4 sm:pl-14">
                      <table className="w-full max-w-3xl text-sm">
                        <thead><tr className="text-left text-xs uppercase tracking-wide text-ink-muted"><th className="pb-2 pr-4 font-semibold">Field</th><th className="pb-2 pr-4 font-semibold">Before</th><th className="pb-2 font-semibold">After</th></tr></thead>
                        <tbody>
                          {changes.map((c) => (
                            <tr key={c.field} className="border-t border-border/60">
                              <td className="py-2 pr-4 font-medium">{c.field}</td>
                              <td className="py-2 pr-4 break-all text-ink-muted">{c.before}</td>
                              <td className="py-2 break-all">{c.after}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </Td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </Table>
      {data?.items.length === 0 && <EmptyState title="No audit entries match" />}
      {data && <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />}
    </div>
  )
}
