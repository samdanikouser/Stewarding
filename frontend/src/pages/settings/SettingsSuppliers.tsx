import { Mail, Pencil, Phone, Plus, Power, Trash2, User } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { CardGrid, RecordCard, SectionHeader } from '@/components/ui/record-card'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface Supplier {
  id: number
  name: string
  contact: string | null
  phone: string | null
  email: string | null
  active: boolean
}

const BLANK = { id: null as number | null, name: '', contact: '', phone: '', email: '' }

function Detail({ icon: Icon, children }: { icon: typeof Mail; children: string | null }) {
  return (
    <span className="flex items-center gap-2 text-ink-muted">
      <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{children || '-'}</span>
    </span>
  )
}

export function SettingsSuppliers() {
  const run = useRun()
  const { data, reload } = useApi<Supplier[]>('/suppliers?include_inactive=true')
  const [form, setForm] = useState<typeof BLANK | null>(null)
  const [removing, setRemoving] = useState<Supplier | null>(null)

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!form) return
    const body = { name: form.name, contact: form.contact || null, phone: form.phone || null, email: form.email || null }
    const ok = await run(() => form.id ? api(`/suppliers/${form.id}`, { method: 'PUT', body }) : api('/suppliers', { body }), 'Supplier saved')
    if (ok) {
      setForm(null)
      reload()
    }
  }

  async function setActive(s: Supplier) {
    if (await run(() => api(`/suppliers/${s.id}`, { method: 'PUT', body: { active: !s.active } }), s.active ? 'Supplier made inactive' : 'Supplier made active')) reload()
  }

  async function remove() {
    if (!removing) return
    const done = await run(() => api(`/suppliers/${removing.id}`, { method: 'DELETE' }), 'Supplier deleted')
    setRemoving(null)
    if (done) reload()
  }

  if (!data) return <Skeleton className="h-48 w-full" />
  return (
    <div className="space-y-6">
      <SectionHeader title="Suppliers" count={data.length} action={<Button onClick={() => setForm({ ...BLANK })}><Plus className="h-4 w-4" /> Add supplier</Button>} />

      {data.length === 0 ? <EmptyState title="No suppliers yet" /> : (
        <CardGrid>
          {data.map((s) => (
            <RecordCard
              key={s.id}
              title={s.name}
              inactive={!s.active}
              badges={<Badge tone={s.active ? 'ok' : 'neutral'}>{s.active ? 'Active' : 'Inactive'}</Badge>}
              facts={[]}
              actions={[
                { label: 'Edit', icon: Pencil, onClick: () => setForm({ id: s.id, name: s.name, contact: s.contact ?? '', phone: s.phone ?? '', email: s.email ?? '' }) },
                { label: s.active ? 'Make inactive' : 'Make active', icon: Power, onClick: () => setActive(s) },
                { label: 'Delete', icon: Trash2, tone: 'danger', onClick: () => setRemoving(s) },
              ]}
              subtitle={undefined}
            >
              <div className="space-y-1.5 text-sm">
                <Detail icon={User}>{s.contact}</Detail>
                <Detail icon={Phone}>{s.phone}</Detail>
                <Detail icon={Mail}>{s.email}</Detail>
              </div>
            </RecordCard>
          ))}
        </CardGrid>
      )}

      <Modal
        open={form !== null}
        title={form?.id ? 'Edit supplier' : 'Add supplier'}
        description="Who goods are bought from, and how to reach them."
        onClose={() => setForm(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setForm(null)}>Cancel</Button>
          <Button type="submit" form="supplier-form">Save supplier</Button>
        </>}
      >
        {form && (
          <form id="supplier-form" onSubmit={save} className="space-y-5">
            <Field label="Name"><Input required minLength={2} maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Contact person"><Input maxLength={120} value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} /></Field>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Phone"><Input maxLength={40} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
              <Field label="Email"><Input type="email" maxLength={200} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removing !== null} title="Delete supplier" confirmLabel="Delete supplier"
        message={`Delete ${removing?.name ?? 'this supplier'}? This cannot be undone. A supplier that items, receipts or food lots already use cannot be deleted; make it inactive instead.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
