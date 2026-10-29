import { ManagedList } from '@/components/ManagedList'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'

interface Row {
  id: number
  name: string
  active: boolean
}

function CategoryList() {
  const run = useRun()
  const { data, reload } = useApi<Row[]>(`/inventory/categories${qs({ include_inactive: true })}`)
  const act = async (call: () => Promise<unknown>, ok: string) => {
    const done = await run(call, ok)
    if (done) reload()
    return done
  }
  return (
    <Card>
      <CardHeader className="p-6 pb-3"><CardTitle className="text-lg">Categories</CardTitle></CardHeader>
      <CardContent className="p-6 pt-3">
        <ManagedList
          entries={data ?? []} placeholder="New category"
          onAdd={(name) => act(() => api('/inventory/categories', { body: { name } }), 'Category added')}
          onRename={(id, name) => act(() => api(`/inventory/categories/${id}`, { method: 'PUT', body: { name } }), 'Category renamed')}
          onToggle={(id, active) => act(() => api(`/inventory/categories/${id}`, { method: 'PUT', body: { active } }), active ? 'Category made active' : 'Category made inactive')}
          onDelete={(id) => act(() => api(`/inventory/categories/${id}`, { method: 'DELETE' }), 'Category deleted')} noun="category"
        />
      </CardContent>
    </Card>
  )
}

function UnitList() {
  const run = useRun()
  const { data, reload } = useApi<Row[]>('/inventory/units?include_inactive=true')
  const act = async (call: () => Promise<unknown>, ok: string) => {
    const done = await run(call, ok)
    if (done) reload()
    return done
  }
  return (
    <Card>
      <CardHeader className="p-6 pb-3"><CardTitle className="text-lg">Units of measure</CardTitle></CardHeader>
      <CardContent className="p-6 pt-3">
        <ManagedList
          entries={data ?? []} placeholder="New unit, e.g. Box"
          onAdd={(name) => act(() => api('/inventory/units', { body: { name } }), 'Unit added')}
          onRename={(id, name) => act(() => api(`/inventory/units/${id}`, { method: 'PUT', body: { name } }), 'Unit renamed')}
          onToggle={(id, active) => act(() => api(`/inventory/units/${id}`, { method: 'PUT', body: { active } }), active ? 'Unit made active' : 'Unit made inactive')}
          onDelete={(id) => act(() => api(`/inventory/units/${id}`, { method: 'DELETE' }), 'Unit deleted')} noun="unit"
        />
      </CardContent>
    </Card>
  )
}

export function SettingsInventoryLists() {
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <CategoryList />
        <UnitList />
      </div>
    </div>
  )
}
