import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { SECTION_TITLES, SETTINGS, type RulesSection } from '@/pages/settings/settingsRegistry'

interface Loaded {
  settings: Record<string, number>
  limits: Record<string, [number, number]>
}

/** The rules of one topic: switches and numbers with their units, saved together from a bar that shows what changed. */
export function SettingsRules({ section }: { section: RulesSection }) {
  const run = useRun()
  const { data, reload } = useApi<Loaded>('/settings')
  const [draft, setDraft] = useState<Record<string, string>>({})
  if (!data) return <Skeleton className="h-64 w-full" />

  const defs = SETTINGS.filter((s) => s.section === section)
  const value = (key: string) => draft[key] ?? String(data.settings[key])
  const changed = defs.filter((d) => value(d.key) !== String(data.settings[d.key]))
  const valid = (key: string) => {
    const [low, high] = data.limits[key]
    const number = Number(value(key))
    return value(key).trim() !== '' && Number.isInteger(number) && number >= low && number <= high
  }
  const invalid = changed.filter((d) => !valid(d.key))

  async function save() {
    const values = Object.fromEntries(changed.map((d) => [d.key, Number(value(d.key))]))
    if (await run(() => api('/settings', { method: 'PUT', body: { values } }), 'Settings saved')) {
      setDraft({})
      reload()
    }
  }

  const toggles = defs.filter((d) => d.kind === 'toggle')
  const numbers = defs.filter((d) => d.kind === 'number')
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">{SECTION_TITLES[section]}</h2>

      {toggles.length > 0 && (
        <Card>
          <CardContent className="divide-y divide-border py-0">
            {toggles.map((d) => (
              <div key={d.key} className="flex min-h-16 items-center justify-between gap-4 py-3">
                <span className="text-[15px] font-medium">{d.label}</span>
                <Switch label={d.label} checked={value(d.key) === '1'} onChange={(on) => setDraft((v) => ({ ...v, [d.key]: on ? '1' : '0' }))} />
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {numbers.length > 0 && (
        <Card>
          <CardContent className="grid gap-5 pt-6 sm:grid-cols-2">
            {numbers.map((d) => {
              const [low, high] = data.limits[d.key]
              return (
                <label key={d.key} className="block space-y-1 text-sm font-medium">
                  {d.label}
                  <span className="flex">
                    <Input
                      type="number"
                      min={low}
                      max={high}
                      step={1}
                      className="rounded-r-none"
                      aria-invalid={changed.includes(d) && !valid(d.key)}
                      value={value(d.key)}
                      onChange={(e) => setDraft((v) => ({ ...v, [d.key]: e.target.value }))}
                    />
                    {d.unit && <span className="flex items-center whitespace-nowrap rounded-r-md border border-l-0 border-border-strong bg-surface-muted px-3 text-sm font-normal text-ink-muted">{d.unit}</span>}
                  </span>
                  {changed.includes(d) && !valid(d.key) && <span role="alert" className="block text-xs font-normal text-danger">Enter a whole number from {low} to {high}</span>}
                </label>
              )
            })}
          </CardContent>
        </Card>
      )}

      {changed.length > 0 && (
        <div role="region" aria-label="Unsaved changes" className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3 shadow-lg">
          <span className="text-sm font-medium">{changed.length} unsaved {changed.length === 1 ? 'change' : 'changes'}</span>
          <span className="flex gap-2">
            <Button variant="outline" onClick={() => setDraft({})}>Discard</Button>
            <Button onClick={save} disabled={invalid.length > 0}>Save changes</Button>
          </span>
        </div>
      )}
    </div>
  )
}
