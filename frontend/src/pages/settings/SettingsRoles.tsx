import { Copy, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { CardGrid, RecordCard, SectionHeader } from '@/components/ui/record-card'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface RoleRow {
  id: number
  name: string
  label: string
  tier: string
  builtin: boolean
  permissions: string[]
  users: number
  defaults: string[] | null
}

interface Catalog {
  tiers: string[]
  groups: { group: string; permissions: { key: string; label: string }[] }[]
}

interface Draft {
  id: number | null
  label: string
  tier: string
  builtin: boolean
  defaults: string[] | null
  permissions: string[]
}

const tierName = (tier: string) => (tier === 'manager' ? 'Manager' : tier === 'supervisor' ? 'Supervisor' : 'Steward')

function whyNoDelete(role: RoleRow): string | undefined {
  if (role.builtin) return 'Built-in roles cannot be deleted'
  if (role.users > 0) return `Move the ${role.users} ${role.users === 1 ? 'person' : 'people'} with this role to another role first`
  return undefined
}

export function SettingsRoles() {
  const run = useRun()
  const roles = useApi<RoleRow[]>('/roles')
  const catalog = useApi<Catalog>('/roles/catalog')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [removing, setRemoving] = useState<RoleRow | null>(null)

  const chosen = new Set(draft?.permissions)
  const toggle = (keys: string[], on: boolean) =>
    setDraft((d) => d && { ...d, permissions: [...new Set(on ? [...d.permissions, ...keys] : d.permissions.filter((p) => !keys.includes(p)))] })

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!draft) return
    const body = { label: draft.label, tier: draft.tier, permissions: draft.permissions }
    const ok = await run(() => api(draft.id ? `/roles/${draft.id}` : '/roles', { method: draft.id ? 'PUT' : 'POST', body }), 'Role saved')
    if (ok) {
      setDraft(null)
      roles.reload()
    }
  }

  async function remove() {
    if (!removing) return
    const done = await run(() => api(`/roles/${removing.id}`, { method: 'DELETE' }), 'Role deleted')
    setRemoving(null)
    if (done) roles.reload()
  }

  if (!roles.data || !catalog.data) return <Skeleton className="h-48 w-full" />
  const total = catalog.data.groups.reduce((n, g) => n + g.permissions.length, 0)
  return (
    <div className="space-y-6">
      <SectionHeader title="Roles" count={roles.data.length}
        action={<Button onClick={() => setDraft({ id: null, label: '', tier: 'supervisor', builtin: false, defaults: null, permissions: ['dashboard.view', 'notification.view'] })}><Plus className="h-4 w-4" /> New role</Button>} />

      <CardGrid>
        {roles.data.map((r) => (
          <RecordCard
            key={r.id}
            title={r.label}
            subtitle={`Behaves like a ${tierName(r.tier).toLowerCase()}`}
            badges={r.builtin ? <Badge>Built in</Badge> : <Badge tone="ok">Custom</Badge>}
            facts={[
              { label: 'People', value: r.users },
              { label: 'Permissions', value: `${r.permissions.length} of ${total}` },
            ]}
            actions={[
              ...(r.name !== 'manager' ? [{ label: 'Edit', icon: Pencil, onClick: () => setDraft({ id: r.id, label: r.label, tier: r.tier, builtin: r.builtin, defaults: r.defaults, permissions: r.permissions }) }] : []),
              { label: 'Copy', icon: Copy, onClick: () => setDraft({ id: null, label: `${r.label} copy`, tier: r.tier === 'manager' ? 'supervisor' : r.tier, builtin: false, defaults: null, permissions: r.permissions }) },
              { label: 'Delete', icon: Trash2, tone: 'danger' as const, disabled: whyNoDelete(r) !== undefined, title: whyNoDelete(r), onClick: () => setRemoving(r) },
            ]}
          />
        ))}
      </CardGrid>

      <Modal
        size="xl"
        open={draft !== null}
        title={draft?.id ? 'Edit role' : 'New role'}
        description="Choose what people with this role can see and do."
        onClose={() => setDraft(null)}
        footer={draft && <>
          <span className="mr-auto text-sm text-ink-muted">{draft.permissions.length} of {total} permissions chosen</span>
          {draft.defaults && <Button type="button" variant="ghost" onClick={() => setDraft({ ...draft, permissions: draft.defaults ?? draft.permissions })}>Restore defaults</Button>}
          <Button type="button" variant="outline" onClick={() => setDraft(null)}>Cancel</Button>
          <Button type="submit" form="role-form" disabled={draft.permissions.length === 0}>Save role</Button>
        </>}
      >
        {draft && (
          <form id="role-form" onSubmit={save} className="space-y-6">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Role name"><Input required minLength={2} maxLength={80} placeholder="Head chef" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} /></Field>
              <Field label="Behaves like">
                <Select value={draft.tier} disabled={draft.builtin} onChange={(e) => setDraft({ ...draft, tier: e.target.value })}>
                  {catalog.data.tiers.map((t) => <option key={t} value={t}>{tierName(t)}</option>)}
                </Select>
              </Field>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              {catalog.data.groups.map((g) => {
                const keys = g.permissions.map((p) => p.key)
                const count = keys.filter((k) => chosen.has(k)).length
                return (
                  <fieldset key={g.group} className="rounded-xl border border-border p-4">
                    <legend className="px-2 text-sm font-semibold">{g.group}</legend>
                    <div className="mb-3 flex items-center justify-between">
                      <label className="flex items-center gap-2 text-sm text-ink-muted">
                        <input type="checkbox" checked={count === keys.length} onChange={(e) => toggle(keys, e.target.checked)} /> Select all
                      </label>
                      <span className="text-xs text-ink-muted">{count} of {keys.length}</span>
                    </div>
                    <div className="space-y-2">
                      {g.permissions.map((p) => (
                        <label key={p.key} className="flex items-center gap-2.5 text-sm">
                          <input type="checkbox" checked={chosen.has(p.key)} onChange={(e) => toggle([p.key], e.target.checked)} /> {p.label}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                )
              })}
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removing !== null} title="Delete role" confirmLabel="Delete role"
        message={`Delete ${removing?.label ?? 'this role'}? This cannot be undone. Nobody has it now.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
