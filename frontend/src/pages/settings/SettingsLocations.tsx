import { MapPin, Pencil, Plus, Power, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { TimezoneInput } from '@/components/TimezoneInput'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { CardGrid, RecordCard, SectionHeader } from '@/components/ui/record-card'
import { Select } from '@/components/ui/select'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { currentPosition } from '@/lib/geo'
import { label } from '@/lib/format'
import { useRun, useToast } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface LocationRow {
  id: number
  code: string
  name: string
  kind: string
  timezone: string
  active: boolean
  latitude: number | null
  longitude: number | null
  geofence_radius_m: number | null
  geofence: boolean
}

const KINDS = ['kitchen', 'restaurant', 'bar', 'banquet', 'station', 'other']
const BLANK = { id: null as number | null, code: '', name: '', kind: 'kitchen', timezone: 'Asia/Kuwait', latitude: '', longitude: '', radius: '' }

export function SettingsLocations() {
  const run = useRun()
  const toast = useToast()
  const { data, reload } = useApi<{ locations: LocationRow[] }>('/settings')
  const [loc, setLoc] = useState<typeof BLANK | null>(null)
  const [removing, setRemoving] = useState<LocationRow | null>(null)
  const org = useApi<{ timezone: string }>('/organization')
  const { refresh } = useAuth()

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!loc) return
    const fence = { latitude: loc.latitude === '' ? null : Number(loc.latitude), longitude: loc.longitude === '' ? null : Number(loc.longitude), geofence_radius_m: loc.radius === '' ? null : Number(loc.radius) }
    const body = loc.id
      ? { name: loc.name, kind: loc.kind, timezone: loc.timezone, ...fence }
      : { code: loc.code, name: loc.name, kind: loc.kind, timezone: loc.timezone, ...fence }
    const ok = await run(() => api(loc.id ? `/settings/locations/${loc.id}` : '/settings/locations', { method: loc.id ? 'PUT' : 'POST', body }), 'Location saved')
    if (ok) {
      setLoc(null)
      reload()
      await refresh()
    }
  }

  async function setActive(l: LocationRow) {
    if (await run(() => api(`/settings/locations/${l.id}`, { method: 'PUT', body: { active: !l.active } }), l.active ? 'Location made inactive' : 'Location made active')) {
      reload()
      await refresh()
    }
  }

  async function remove() {
    if (!removing) return
    const done = await run(() => api(`/settings/locations/${removing.id}`, { method: 'DELETE' }), 'Location deleted')
    setRemoving(null)
    if (done) {
      reload()
      await refresh()
    }
  }

  async function useHere() {
    if (!loc) return
    try {
      const here = await currentPosition()
      setLoc({ ...loc, latitude: here.latitude.toFixed(6), longitude: here.longitude.toFixed(6), radius: loc.radius || '100' })
    } catch (err) {
      toast('error', err instanceof Error ? err.message : 'Could not read your position')
    }
  }

  const edit = (l: LocationRow) => setLoc({ ...BLANK, id: l.id, code: l.code, name: l.name, kind: l.kind, timezone: l.timezone,
    latitude: l.latitude === null ? '' : String(l.latitude), longitude: l.longitude === null ? '' : String(l.longitude), radius: l.geofence_radius_m === null ? '' : String(l.geofence_radius_m) })

  if (!data) return <Skeleton className="h-48 w-full" />
  return (
    <div className="space-y-6">
      <SectionHeader title="Locations" count={data.locations.length}
        action={<Button onClick={() => setLoc({ ...BLANK, timezone: org.data?.timezone ?? BLANK.timezone })}><Plus className="h-4 w-4" /> Add location</Button>} />

      {data.locations.length === 0 ? <EmptyState title="No locations yet" /> : (
        <CardGrid>
          {data.locations.map((l) => (
            <RecordCard
              key={l.id}
              title={l.name}
              subtitle={l.code}
              inactive={!l.active}
              badges={<Badge tone={l.active ? 'ok' : 'neutral'}>{l.active ? 'Active' : 'Inactive'}</Badge>}
              facts={[
                { label: 'Type', value: label(l.kind) },
                { label: 'Time zone', value: l.timezone },
                { label: 'Check-in area', value: l.geofence ? `Within ${l.geofence_radius_m} m` : 'Anywhere' },
              ]}
              actions={[
                { label: 'Edit', icon: Pencil, onClick: () => edit(l) },
                { label: l.active ? 'Make inactive' : 'Make active', icon: Power, onClick: () => setActive(l) },
                { label: 'Delete', icon: Trash2, tone: 'danger', onClick: () => setRemoving(l) },
              ]}
            />
          ))}
        </CardGrid>
      )}

      <Modal
        open={loc !== null}
        title={loc?.id ? 'Edit location' : 'Add location'}
        description={loc?.id ? 'Change how this location is named, timed and checked in to.' : 'A kitchen, bar, banquet hall or any place the team works.'}
        size="lg"
        onClose={() => setLoc(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setLoc(null)}>Cancel</Button>
          <Button type="submit" form="location-form">Save location</Button>
        </>}
      >
        {loc && (
          <form id="location-form" onSubmit={save} className="space-y-6">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Code"><Input required disabled={loc.id !== null} maxLength={20} value={loc.code} onChange={(e) => setLoc({ ...loc, code: e.target.value })} /></Field>
              <Field label="Name"><Input required value={loc.name} onChange={(e) => setLoc({ ...loc, name: e.target.value })} /></Field>
              <Field label="Type"><Select value={loc.kind} onChange={(e) => setLoc({ ...loc, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
              <Field label="Time zone"><TimezoneInput value={loc.timezone} onChange={(zone) => setLoc({ ...loc, timezone: zone })} /></Field>
            </div>
            <fieldset className="space-y-4 rounded-xl border border-border p-4">
              <legend className="flex items-center gap-2 px-2 text-sm font-semibold"><MapPin aria-hidden className="h-4 w-4 text-brand" /> Limit check-in and check-out to an area</legend>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Latitude"><Input type="number" step="any" min={-90} max={90} value={loc.latitude} onChange={(e) => setLoc({ ...loc, latitude: e.target.value })} /></Field>
                <Field label="Longitude"><Input type="number" step="any" min={-180} max={180} value={loc.longitude} onChange={(e) => setLoc({ ...loc, longitude: e.target.value })} /></Field>
                <Field label="Radius (metres)"><Input type="number" min={20} max={5000} value={loc.radius} onChange={(e) => setLoc({ ...loc, radius: e.target.value })} /></Field>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="outline" onClick={useHere}>Use my current position</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setLoc({ ...loc, latitude: '', longitude: '', radius: '' })}>Remove restriction</Button>
              </div>
            </fieldset>
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removing !== null} title="Delete location" confirmLabel="Delete location"
        message={`Delete ${removing?.name ?? 'this location'}? This cannot be undone. A location that people, stock, checklists or readings already use cannot be deleted; make it inactive instead.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
