import { Pencil, Plus, Power, Printer as PrinterIcon, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { CardGrid, RecordCard, SectionHeader } from '@/components/ui/record-card'
import { Select } from '@/components/ui/select'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

interface Printer {
  id: number
  name: string
  host: string
  port: number
  dpi: number
  active: boolean
}

interface Draft {
  id: number | null
  name: string
  host: string
  port: string
  dpi: string
}

const BLANK: Draft = { id: null, name: '', host: '', port: '9100', dpi: '203' }

/** Network Zebra printers the server sends labels to; a manager adds each by its address and checks it with a test label. */
export function PrintersTab() {
  const run = useRun()
  const { data, reload } = useApi<Printer[]>('/label-printers')
  const [form, setForm] = useState<Draft | null>(null)
  const [removing, setRemoving] = useState<Printer | null>(null)

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!form) return
    const body = { name: form.name, host: form.host, port: Number(form.port), dpi: Number(form.dpi) }
    const ok = await run(() => form.id ? api(`/label-printers/${form.id}`, { method: 'PUT', body: { ...body, active: data?.find((p) => p.id === form.id)?.active ?? true } }) : api('/label-printers', { body }), form.id ? 'Printer updated' : 'Printer added')
    if (ok) {
      setForm(null)
      reload()
    }
  }

  const setActive = async (p: Printer) => {
    if (await run(() => api(`/label-printers/${p.id}`, { method: 'PUT', body: { name: p.name, host: p.host, port: p.port, dpi: p.dpi, active: !p.active } }), p.active ? 'Printer switched off' : 'Printer switched on')) reload()
  }
  const remove = async () => {
    if (!removing) return
    const done = await run(() => api(`/label-printers/${removing.id}`, { method: 'DELETE' }), 'Printer deleted')
    setRemoving(null)
    if (done) reload()
  }
  const test = (p: Printer) => run(() => api(`/label-printers/${p.id}/test`, { method: 'POST', body: {} }), `Test label sent to ${p.name}`)

  if (!data) return <Skeleton className="h-48 w-full" />
  return (
    <div className="space-y-6">
      <SectionHeader title="Label printers" count={data.length} action={<Button onClick={() => setForm({ ...BLANK })}><Plus className="h-4 w-4" /> Add printer</Button>} />

      {data.length === 0 ? <EmptyState title="No label printers yet" /> : (
        <CardGrid>
          {data.map((p) => (
            <RecordCard
              key={p.id}
              title={p.name}
              subtitle={`${p.host}:${p.port}`}
              inactive={!p.active}
              badges={<Badge tone={p.active ? 'ok' : 'neutral'}>{p.active ? 'On' : 'Off'}</Badge>}
              facts={[{ label: 'Resolution', value: `${p.dpi} dpi` }]}
              actions={[
                { label: 'Test label', icon: PrinterIcon, onClick: () => test(p), disabled: !p.active, title: p.active ? undefined : 'Switch the printer on first' },
                { label: 'Edit', icon: Pencil, onClick: () => setForm({ id: p.id, name: p.name, host: p.host, port: String(p.port), dpi: String(p.dpi) }) },
                { label: p.active ? 'Switch off' : 'Switch on', icon: Power, onClick: () => setActive(p) },
                { label: 'Delete', icon: Trash2, tone: 'danger', onClick: () => setRemoving(p) },
              ]}
            />
          ))}
        </CardGrid>
      )}

      <Modal
        open={form !== null}
        size="md"
        title={form?.id ? 'Edit printer' : 'Add printer'}
        description="A Zebra printer on your network, found by its address."
        onClose={() => setForm(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setForm(null)}>Cancel</Button>
          <Button type="submit" form="printer-form">Save printer</Button>
        </>}
      >
        {form && (
          <form id="printer-form" onSubmit={save} className="space-y-5">
            <Field label="Name"><Input required minLength={2} maxLength={60} placeholder="Butchery Zebra" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="IP address or network name"><Input required maxLength={120} placeholder="192.168.1.50" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} /></Field>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Port"><Input required type="number" min={1} max={65535} value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} /></Field>
              <Field label="Resolution">
                <Select value={form.dpi} onChange={(e) => setForm({ ...form, dpi: e.target.value })}>
                  <option value="203">203 dpi</option>
                  <option value="300">300 dpi</option>
                  <option value="600">600 dpi</option>
                </Select>
              </Field>
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removing !== null} title="Delete printer" confirmLabel="Delete printer"
        message={`Delete ${removing?.name ?? 'this printer'}? Labels can no longer be sent to it. You can add it again later.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
