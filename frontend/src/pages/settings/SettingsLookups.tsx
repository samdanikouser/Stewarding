import { ManagedList } from '@/components/ManagedList'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import type { LookupKind } from '@/lib/useLookups'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface Row {
  id: number
  value: string
  active: boolean
}

const LISTS: { kind: LookupKind; title: string; placeholder: string }[] = [
  { kind: 'job_title', title: 'Job titles', placeholder: 'New job title' },
  { kind: 'checklist_category', title: 'Checklist categories', placeholder: 'New category' },
  { kind: 'breakage_reason', title: 'Breakage reasons', placeholder: 'New reason' },
  { kind: 'corrective_action', title: 'Standard corrective actions', placeholder: 'New standard action' },
  { kind: 'monitoring_type', title: 'Monitoring types', placeholder: 'New monitoring type' },
]

function Lookup({ kind, title, placeholder }: (typeof LISTS)[number]) {
  const run = useRun()
  const { data, reload } = useApi<Row[]>(`/lookups?kind=${kind}&include_inactive=true`)
  const act = async (call: () => Promise<unknown>, ok: string) => {
    const done = await run(call, ok)
    if (done) reload()
    return done
  }
  return (
    <Card>
      <CardHeader className="p-6 pb-3">
        <CardTitle className="text-lg">{title}</CardTitle>
      </CardHeader>
      <CardContent className="p-6 pt-3">
        <ManagedList
          entries={(data ?? []).map((r) => ({ id: r.id, name: r.value, active: r.active }))} placeholder={placeholder}
          onAdd={(value) => act(() => api('/lookups', { body: { kind, value } }), 'Added')}
          onRename={(id, value) => act(() => api(`/lookups/${id}`, { method: 'PUT', body: { value } }), 'Renamed')}
          onToggle={(id, active) => act(() => api(`/lookups/${id}`, { method: 'PUT', body: { active } }), active ? 'Made active' : 'Made inactive')}
          onDelete={(id) => act(() => api(`/lookups/${id}`, { method: 'DELETE' }), 'Deleted')} noun="value"
        />
      </CardContent>
    </Card>
  )
}

export function SettingsLookups() {
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">{LISTS.map((l) => <Lookup key={l.kind} {...l} />)}</div>
    </div>
  )
}
