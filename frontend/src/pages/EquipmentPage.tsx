import { Plus, Wrench } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { LocationSelect } from '@/components/LocationSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/utils'
import { label } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { CheckFormModal } from '@/pages/CheckFormModal'
import { FormBuilderModal } from '@/pages/FormBuilderModal'
import type { EquipmentItem, Schedule } from '@/pages/MonitoringRecordForm'

interface Template {
  key: string
  name: string
  type: string
  checks: { stage: string; parameter: string; unit: string | null; value_type: string; min_value: number | null; max_value: number | null; timing: string; phase: string | null }[]
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function when(s: Schedule): string {
  if (s.phase === 'finish') return 'When the time in entry is closed'
  const days = s.weekdays.length ? s.weekdays.map((d) => DAYS[d]).join(', ') : 'Every day'
  const month = s.day_of_month ? `day ${s.day_of_month} of the month` : days
  const timing = s.timing === 'interval' ? `every ${s.interval_minutes} min` : s.timing === 'startup' ? 'at startup' : 'at a set time'
  return `${month}, ${timing}${s.time_of_day ? ` from ${s.time_of_day.slice(0, 5)}` : ''}`
}

function limits(s: Schedule): string {
  if (s.value_type === 'yes_no') return 'Must be Yes'
  if (s.value_type === 'text') return `Written, up to ${s.max_length ?? 200} characters`
  if (s.value_type === 'choice') return `Choose: ${(s.options ?? []).join(', ')}${s.fail_options?.length ? ` (fails: ${s.fail_options.join(', ')})` : ''}`
  return `${s.min_value ?? '-'} to ${s.max_value ?? '-'} ${s.unit ?? ''}`.trim()
}

export function EquipmentPage({ embedded = false }: { embedded?: boolean }) {
  const { me } = useAuth()
  const run = useRun()
  const canManage = me?.permissions.includes('equipment.manage') ?? false
  const [locationId, setLocationId] = useState<number | null>(null)
  const { data, reload } = useApi<EquipmentItem[]>(locationId ? `/equipment${qs({ location_id: locationId })}` : null)
  const [editing, setEditing] = useState<{ equipmentId: number; schedule: Schedule | null } | null>(null)
  const [adding, setAdding] = useState(false)
  const [deleting, setDeleting] = useState<{ kind: 'point' | 'check'; id: number; name: string } | null>(null)
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null)
  const [presetOpen, setPresetOpen] = useState(false)
  const [preset, setPreset] = useState('')
  const [presetName, setPresetName] = useState('')
  const templates = useApi<Template[]>(canManage ? '/equipment/templates' : null)
  const chosen = templates.data?.find((t) => t.key === preset)

  async function setStatus(eq: EquipmentItem, status: string) {
    if (await run(() => api(`/equipment/${eq.id}`, { method: 'PUT', body: { status } }), 'Status updated')) reload()
  }

  async function setPointActive(eq: EquipmentItem) {
    if (await run(() => api(`/equipment/${eq.id}`, { method: 'PUT', body: { active: !eq.active } }), eq.active ? 'Made inactive' : 'Made active')) reload()
  }

  async function setCheckActive(s: Schedule) {
    if (await run(() => api(`/equipment/schedules/${s.id}/active`, { method: 'PUT', body: { active: !s.active } }), s.active ? 'Made inactive' : 'Made active')) reload()
  }

  async function confirmDelete() {
    if (!deleting) return
    const path = deleting.kind === 'point' ? `/equipment/${deleting.id}` : `/equipment/schedules/${deleting.id}`
    if (await run(() => api(path, { method: 'DELETE' }), 'Deleted')) {
      setDeleting(null)
      reload()
    }
  }

  async function rename(event: FormEvent) {
    event.preventDefault()
    if (renaming && await run(() => api(`/equipment/${renaming.id}`, { method: 'PUT', body: { name: renaming.name.trim() } }), 'Name updated')) {
      setRenaming(null)
      reload()
    }
  }

  async function addFromTemplate(event: FormEvent) {
    event.preventDefault()
    const ok = await run(() => api('/equipment/from-template', { body: { template: preset, location_id: locationId, name: presetName || null } }), 'Monitoring point added')
    if (ok) {
      setPresetOpen(false)
      setPreset('')
      setPresetName('')
      reload()
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {embedded ? <h2 className="text-lg font-semibold">Monitoring points and checks</h2> : <h1 className="text-2xl font-semibold">Monitoring Setup</h1>}
        <div className="flex flex-wrap gap-3">
          <LocationSelect value={locationId} onChange={setLocationId} />
          {canManage && <Button onClick={() => setPresetOpen(true)}><Plus className="h-4 w-4" /> From template</Button>}
          {canManage && <Button variant="outline" onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> Create form</Button>}
        </div>
      </div>

      {data?.length === 0 && <EmptyState title="No monitoring points at this location" />}
      {data?.map((eq) => (
        <Card key={eq.id} className={cn(eq.needs_attention && 'border-warn/60', !eq.active && 'opacity-70')}>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              <Wrench className="h-4 w-4 text-brand" aria-hidden /> {eq.name}
              <span className="text-sm font-normal text-ink-muted">{eq.code} - {label(eq.kind)}</span>
              <StatusBadge status={eq.status} />
              {!eq.active && <StatusBadge status="inactive" />}
              {eq.needs_attention && <Badge tone="warn">Needs attention ({eq.recent_failures} recent failures)</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5 p-6 pt-3">
            {eq.maintenance_notes && <p className="text-sm text-ink-muted">{eq.maintenance_notes}</p>}
            {canManage && (
              <div className="flex flex-wrap gap-2">
                <Select aria-label={`Status of ${eq.name}`} className="w-auto" value={eq.status} onChange={(e) => setStatus(eq, e.target.value)}>
                  <option value="operational">Operational</option>
                  <option value="attention">Needs attention</option>
                  <option value="out_of_service">Out of service</option>
                </Select>
                <Button size="sm" variant="outline" onClick={() => setRenaming({ id: eq.id, name: eq.name })}>Rename</Button>
                <Button size="sm" variant="outline" className="whitespace-nowrap" onClick={() => setPointActive(eq)}>{eq.active ? 'Make inactive' : 'Make active'}</Button>
                <Button size="sm" variant="outline" onClick={() => setDeleting({ kind: 'point', id: eq.id, name: eq.name })}>Delete</Button>
              </div>
            )}
            <Table>
              <thead><tr><Th>Check</Th><Th>Measures</Th><Th>When</Th><Th>Limits</Th>{canManage && <Th />}</tr></thead>
              <tbody>
                {eq.schedules.map((s) => (
                  <tr key={s.id} className={s.active ? undefined : 'opacity-60'}>
                    <Td>{s.stage}{!s.active && <Badge className="ml-2">Inactive</Badge>}{s.require_reference && <Badge className="ml-2">{s.reference_label ?? 'Reference'}</Badge>}{s.trace_lots && <Badge className="ml-2">Food lots</Badge>}{s.phase && <Badge className="ml-2">{s.phase === 'start' ? 'Time in' : 'Time out'}</Badge>}</Td>
                    <Td>{({ yes_no: 'Yes or no', text: 'Short text', choice: 'Dropdown' } as Record<string, string>)[s.value_type] ?? s.parameter}</Td>
                    <Td>{when(s)}</Td>
                    <Td>{limits(s)}</Td>
                    {canManage && (
                      <Td>
                        <div className="flex flex-wrap gap-2">
                          <Button size="sm" variant="outline" onClick={() => setEditing({ equipmentId: eq.id, schedule: s })}>Edit</Button>
                          <Button size="sm" variant="outline" className="whitespace-nowrap" onClick={() => setCheckActive(s)}>{s.active ? 'Make inactive' : 'Make active'}</Button>
                          <Button size="sm" variant="outline" onClick={() => setDeleting({ kind: 'check', id: s.id, name: s.stage })}>Delete</Button>
                        </div>
                      </Td>
                    )}
                  </tr>
                ))}
              </tbody>
            </Table>
            {canManage && <Button size="sm" variant="outline" onClick={() => setEditing({ equipmentId: eq.id, schedule: null })}>Add check</Button>}
          </CardContent>
        </Card>
      ))}

      <ConfirmDialog open={deleting !== null} title={deleting?.kind === 'point' ? 'Delete monitoring point' : 'Delete check'}
        message={`Delete ${deleting?.name ?? ''}? This cannot be undone. Anything with recorded readings cannot be deleted; make it inactive instead.`}
        confirmLabel="Delete" onConfirm={confirmDelete} onCancel={() => setDeleting(null)} />

      {editing && <CheckFormModal equipmentId={editing.equipmentId} schedule={editing.schedule} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload() }} />}

      <Modal open={presetOpen} title="Add from template" description="A ready-made monitoring point with its checks and limits." onClose={() => setPresetOpen(false)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setPresetOpen(false)}>Cancel</Button>
          <Button type="submit" form="template-form" disabled={!preset || !locationId}>Add monitoring point</Button>
        </>}>
        <form id="template-form" onSubmit={addFromTemplate} className="space-y-5">
          <Field label="Template">
            <Select required value={preset} onChange={(e) => setPreset(e.target.value)}>
              <option value="">Select</option>
              {templates.data?.map((t) => <option key={t.key} value={t.key}>{t.name}</option>)}
            </Select>
          </Field>
          {chosen && (
            <ul className="list-inside list-disc text-sm text-ink-muted">
              {chosen.checks.map((c, i) => (
                <li key={i}>{c.stage}: {c.value_type === 'yes_no' ? 'yes or no' : `${c.parameter} ${c.min_value ?? '-'} to ${c.max_value ?? '-'} ${c.unit ?? ''}`}</li>
              ))}
            </ul>
          )}
          <Field label="Name (optional)"><Input value={presetName} maxLength={120} onChange={(e) => setPresetName(e.target.value)} /></Field>
        </form>
      </Modal>

      <Modal open={renaming !== null} size="sm" title="Rename monitoring point" onClose={() => setRenaming(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setRenaming(null)}>Cancel</Button>
          <Button type="submit" form="rename-form" disabled={!renaming || renaming.name.trim().length < 2}>Save name</Button>
        </>}>
        <form id="rename-form" onSubmit={rename} className="space-y-3">
          <Field label="Name"><Input required minLength={2} maxLength={120} value={renaming?.name ?? ''} onChange={(e) => setRenaming((r) => r && { ...r, name: e.target.value })} /></Field>
        </form>
      </Modal>

      {adding && <FormBuilderModal initialLocation={locationId} onClose={() => setAdding(false)} onCreated={() => { setAdding(false); reload() }} />}
    </div>
  )
}
