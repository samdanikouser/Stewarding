import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { Skeleton, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { RECEIVED_CONDITIONS, type Rules } from '@/pages/trace/types'

/** How long each kind of food keeps in each condition, in hours; the use-by date of a lot is worked out from these. */
export function RulesTab() {
  const { me } = useAuth()
  const run = useRun()
  const { data, reload } = useApi<Rules>('/lots/rules')
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [limits, setLimits] = useState<Record<string, string>>({})
  const canEdit = me?.permissions.includes('lot.manage') ?? false

  if (!data) return <Skeleton className="h-48 w-full" />
  const current = (group: string, condition: string) => data.rules.find((r) => r.food_group === group && r.condition === condition)
  const key = (group: string, condition: string) => `${group}:${condition}`

  async function save(group: string, condition: string) {
    const typed = draft[key(group, condition)]
    const existing = current(group, condition)
    setDraft((d) => Object.fromEntries(Object.entries(d).filter(([k]) => k !== key(group, condition))))
    if (typed === undefined || typed === String(existing?.hours ?? '')) return
    const ok = typed === ''
      ? existing && await run(() => api(`/lots/rules/${existing.id}`, { method: 'DELETE' }), 'Rule removed')
      : await run(() => api('/lots/rules', { method: 'PUT', body: { food_group: group, condition, hours: Number(typed) } }), 'Rule saved')
    if (ok) reload()
  }

  async function saveLimit(condition: string) {
    const typed = limits[condition]
    setLimits((d) => Object.fromEntries(Object.entries(d).filter(([k]) => k !== condition)))
    if (typed === undefined || typed === '' || Number(typed) === data?.cold_chain[condition]) return
    if (await run(() => api('/lots/cold-chain', { method: 'PUT', body: { condition, max_c: Number(typed) } }), 'Limit saved')) reload()
  }

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <h2 className="text-base font-semibold">Shelf life</h2>
        <Table>
          <thead><tr><Th>Food</Th>{data.conditions.map((c) => <Th key={c.key} className="text-right">{c.label} (hours)</Th>)}</tr></thead>
          <tbody>
            {data.groups.map((g) => (
              <tr key={g.key}>
                <Td className="font-medium">{g.label}</Td>
                {data.conditions.map((c) => (
                  <Td key={c.key} className="text-right">
                    <Input
                      aria-label={`${g.label}, ${c.label}, hours`}
                      type="number"
                      min={1}
                      max={8760}
                      disabled={!canEdit}
                      className="ml-auto h-9 w-24 text-right tabular-nums"
                      placeholder="not set"
                      value={draft[key(g.key, c.key)] ?? String(current(g.key, c.key)?.hours ?? '')}
                      onChange={(e) => setDraft((d) => ({ ...d, [key(g.key, c.key)]: e.target.value }))}
                      onBlur={() => save(g.key, c.key)}
                      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
                    />
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
      <div className="space-y-3">
        <h2 className="text-base font-semibold">Warmest arrival temperature</h2>
        <div className="flex flex-wrap gap-4">
          {RECEIVED_CONDITIONS.map(([condition, text]) => (
            <label key={condition} className="text-sm">
              <span className="block pb-1 font-medium">{text} (&deg;C)</span>
              <Input
                aria-label={`${text}, warmest arrival temperature in C`}
                type="number"
                step="0.5"
                min={-60}
                max={30}
                disabled={!canEdit}
                className="h-9 w-28 tabular-nums"
                value={limits[condition] ?? String(data.cold_chain[condition])}
                onChange={(e) => setLimits((d) => ({ ...d, [condition]: e.target.value }))}
                onBlur={() => saveLimit(condition)}
                onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
              />
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}
