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
import type { Rules } from '@/pages/trace/types'

interface FoodItem {
  id: number
  name: string
  food_group: string
  group_label: string
  active: boolean
}

interface Draft {
  id: number | null
  name: string
  group: string
}

/** The foods that can be received, each in a group that decides its shelf life. */
export function FoodItemsTab() {
  const run = useRun()
  const items = useApi<FoodItem[]>('/lots/food-items?include_inactive=true')
  const rules = useApi<Rules>('/lots/rules')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [removing, setRemoving] = useState<FoodItem | null>(null)

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!draft) return
    const body = { name: draft.name, food_group: draft.group }
    const ok = await run(() => draft.id ? api(`/lots/food-items/${draft.id}`, { method: 'PUT', body }) : api('/lots/food-items', { body }), draft.id ? 'Food item updated' : 'Food item added')
    if (ok) {
      setDraft(null)
      items.reload()
    }
  }

  async function setActive(item: FoodItem) {
    if (await run(() => api(`/lots/food-items/${item.id}`, { method: 'PUT', body: { active: !item.active } }), item.active ? 'Food item hidden' : 'Food item shown again')) items.reload()
  }

  async function remove() {
    if (!removing) return
    const done = await run(() => api(`/lots/food-items/${removing.id}`, { method: 'DELETE' }), 'Food item deleted')
    setRemoving(null)
    if (done) items.reload()
  }

  if (!items.data || !rules.data) return <Skeleton className="h-48 w-full" />
  return (
    <div className="space-y-6">
      <SectionHeader title="Food items" count={items.data.length}
        action={<Button onClick={() => setDraft({ id: null, name: '', group: rules.data?.groups[0]?.key ?? 'poultry' })}><Plus className="h-4 w-4" /> Add food item</Button>} />

      {items.data.length === 0 ? <EmptyState title="No food items yet" /> : (
        <CardGrid>
          {items.data.map((i) => (
            <RecordCard
              key={i.id}
              title={i.name}
              subtitle={i.group_label}
              inactive={!i.active}
              badges={<Badge tone={i.active ? 'ok' : 'neutral'}>{i.active ? 'In use' : 'Hidden'}</Badge>}
              actions={[
                { label: 'Edit', icon: Pencil, onClick: () => setDraft({ id: i.id, name: i.name, group: i.food_group }) },
                { label: i.active ? 'Hide' : 'Show', icon: Power, onClick: () => setActive(i) },
                { label: 'Delete', icon: Trash2, tone: 'danger', onClick: () => setRemoving(i) },
              ]}
            />
          ))}
        </CardGrid>
      )}

      <Modal
        open={draft !== null}
        size="md"
        title={draft?.id ? 'Edit food item' : 'Add food item'}
        description="The group decides how long the food keeps."
        onClose={() => setDraft(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setDraft(null)}>Cancel</Button>
          <Button type="submit" form="food-item-form">Save food item</Button>
        </>}
      >
        {draft && (
          <form id="food-item-form" onSubmit={save} className="space-y-5">
            <Field label="Food item"><Input required minLength={2} maxLength={120} placeholder="Chicken breast, skinless" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
            <Field label="Group">
              <Select value={draft.group} onChange={(e) => setDraft({ ...draft, group: e.target.value })}>
                {rules.data?.groups.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
              </Select>
            </Field>
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removing !== null} title="Delete food item" confirmLabel="Delete food item"
        message={`Delete ${removing?.name ?? 'this food item'}? This cannot be undone. One that food lots were received of cannot be deleted; hide it instead.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
