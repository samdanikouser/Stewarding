import { Pencil, Plus, Power, Trash2 } from 'lucide-react'
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

export interface PortionName {
  id: number
  name: string
  food_item_id: number | null
  food_item: string | null
  active: boolean
}

interface Draft {
  id: number | null
  name: string
  foodItem: string
}

/** The names food is portioned under, picked in the split form; a new name typed there is added here by itself. */
export function PortionNamesTab() {
  const run = useRun()
  const portions = useApi<PortionName[]>('/lots/portion-names?include_inactive=true')
  const foods = useApi<{ id: number; name: string }[]>('/lots/food-items')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [removing, setRemoving] = useState<PortionName | null>(null)

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!draft) return
    const body = { name: draft.name, food_item_id: draft.foodItem ? Number(draft.foodItem) : null }
    const ok = await run(() => draft.id ? api(`/lots/portion-names/${draft.id}`, { method: 'PUT', body }) : api('/lots/portion-names', { body }), draft.id ? 'Portion name updated' : 'Portion name added')
    if (ok) {
      setDraft(null)
      portions.reload()
    }
  }

  async function setActive(portion: PortionName) {
    if (await run(() => api(`/lots/portion-names/${portion.id}`, { method: 'PUT', body: { active: !portion.active } }), portion.active ? 'Portion name hidden' : 'Portion name shown again')) portions.reload()
  }

  async function remove() {
    if (!removing) return
    const done = await run(() => api(`/lots/portion-names/${removing.id}`, { method: 'DELETE' }), 'Portion name deleted')
    setRemoving(null)
    if (done) portions.reload()
  }

  if (!portions.data) return <Skeleton className="h-48 w-full" />
  return (
    <div className="space-y-6">
      <SectionHeader title="Portion names" count={portions.data.length}
        action={<Button onClick={() => setDraft({ id: null, name: '', foodItem: '' })}><Plus className="h-4 w-4" /> Add portion name</Button>} />

      {portions.data.length === 0 ? <EmptyState title="No portion names yet - they appear here as people split lots" /> : (
        <CardGrid>
          {portions.data.map((p) => (
            <RecordCard
              key={p.id}
              title={p.name}
              subtitle={p.food_item ?? 'Any food item'}
              inactive={!p.active}
              badges={<Badge tone={p.active ? 'ok' : 'neutral'}>{p.active ? 'In use' : 'Hidden'}</Badge>}
              actions={[
                { label: 'Edit', icon: Pencil, onClick: () => setDraft({ id: p.id, name: p.name, foodItem: p.food_item_id ? String(p.food_item_id) : '' }) },
                { label: p.active ? 'Hide' : 'Show', icon: Power, onClick: () => setActive(p) },
                { label: 'Delete', icon: Trash2, tone: 'danger', onClick: () => setRemoving(p) },
              ]}
            />
          ))}
        </CardGrid>
      )}

      <Modal
        open={draft !== null}
        size="md"
        title={draft?.id ? 'Edit portion name' : 'Add portion name'}
        description="Tie a name to a food item so it is suggested first when that food is split."
        onClose={() => setDraft(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setDraft(null)}>Cancel</Button>
          <Button type="submit" form="portion-name-form">Save portion name</Button>
        </>}
      >
        {draft && (
          <form id="portion-name-form" onSubmit={save} className="space-y-5">
            <Field label="Portion name"><Input required minLength={2} maxLength={120} placeholder="Chicken breast portions" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
            <Field label="Food item (optional)">
              <Select value={draft.foodItem} onChange={(e) => setDraft({ ...draft, foodItem: e.target.value })}>
                <option value="">Any food item</option>
                {foods.data?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </Select>
            </Field>
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removing !== null} title="Delete portion name" confirmLabel="Delete portion name"
        message={`Delete ${removing?.name ?? 'this portion name'}? Lots already portioned under it keep their name. Hide it instead to stop it being suggested.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
