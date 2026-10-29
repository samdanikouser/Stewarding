import { AlertTriangle, ImagePlus } from 'lucide-react'
import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react'
import { ItemThumb } from '@/components/ItemThumb'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { api, uploadItemImage } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { shrinkImage } from '@/lib/image'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import type { Item } from '@/lib/useItems'

interface ItemFormProps {
  item: Item | null
  open: boolean
  onClose: () => void
  onSaved: () => void
}

interface Similar {
  id: number
  code: string
  name: string
  active: boolean
  match: 'same' | 'similar'
}

export function ItemForm({ item, open, onClose, onSaved }: ItemFormProps) {
  const { me } = useAuth()
  const run = useRun()
  const editing = item !== null
  const categories = useApi<{ id: number; name: string }[]>('/inventory/categories')
  const units = useApi<{ id: number; name: string }[]>('/inventory/units')
  const suppliers = useApi<{ id: number; name: string }[]>('/suppliers')
  const [similar, setSimilar] = useState<Similar[]>([])
  const [picture, setPicture] = useState<File | null>(null)
  const [removePicture, setRemovePicture] = useState(false)
  const [otherSuppliers, setOtherSuppliers] = useState<number[]>(item?.supplier_ids ?? [])
  const [form, setForm] = useState({
    name: item?.name ?? '', category_id: item ? String(item.category_id) : '',
    unit_id: item ? String(item.unit_id) : '', supplier_id: item?.supplier_id ? String(item.supplier_id) : '',
    min_level: String(item?.min_level ?? 0), target_level: item?.target_level != null ? String(item.target_level) : '',
    unit_cost: item?.unit_cost != null ? String(item.unit_cost) : '', storage_location: item?.storage_location ?? '',
    is_tracked_asset: item?.is_tracked_asset ?? false, opening_qty: '0', opening_location_id: String(me?.locations[0]?.id ?? ''),
  })
  const set = (key: keyof typeof form, value: string | boolean) => setForm((f) => ({ ...f, [key]: value }))

  // As the name is typed, show existing items with a similar name so a duplicate is noticed before saving.
  useEffect(() => {
    const text = form.name.trim()
    if (text.length < 3) return
    let live = true
    const timer = setTimeout(() => {
      api<Similar[]>(`/inventory/items/lookup${qs({ q: text })}`)
        .then((rows) => live && setSimilar(rows.filter((r) => r.id !== item?.id)))
        .catch(() => live && setSimilar([]))
    }, 250)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [form.name, item?.id])

  const preview = useMemo(() => (picture ? URL.createObjectURL(picture) : null), [picture])
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  async function choosePicture(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setRemovePicture(false)
    setPicture(await shrinkImage(file))
  }

  const hasPicture = picture !== null || (item?.image_path != null && !removePicture)

  const shownSimilar = form.name.trim().length >= 3 ? similar : []
  const exact = shownSimilar.find((s) => s.match === 'same')

  async function submit(event: FormEvent) {
    event.preventDefault()
    const common = {
      name: form.name, category_id: Number(form.category_id), unit_id: Number(form.unit_id),
      supplier_id: form.supplier_id ? Number(form.supplier_id) : null, supplier_ids: otherSuppliers.filter((id) => String(id) !== form.supplier_id), min_level: Number(form.min_level),
      target_level: form.target_level === '' ? null : Number(form.target_level),
      unit_cost: form.unit_cost === '' ? null : Number(form.unit_cost), storage_location: form.storage_location || null,
    }
    const ok = await run(async () => {
      const saved = editing
        ? await api<{ id: number }>(`/inventory/items/${item.id}`, { method: 'PUT', body: common })
        : await api<{ id: number }>('/inventory/items', { body: { ...common, is_tracked_asset: form.is_tracked_asset,
          opening_qty: Number(form.opening_qty), opening_location_id: Number(form.opening_qty) > 0 ? Number(form.opening_location_id) : null } })
      if (picture) await uploadItemImage(saved.id, picture)
      else if (removePicture && item?.image_path) await api(`/inventory/items/${saved.id}/image`, { method: 'DELETE' })
    }, editing ? 'Item updated' : 'Item created')
    if (ok) onSaved()
  }

  return (
    <Modal
      open={open}
      size="lg"
      title={editing ? 'Edit item' : 'Add item to the item master'}
      description={editing ? item.code : 'Every item gets its own generated ID when it is saved.'}
      onClose={onClose}
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="item-form" disabled={!!exact}>{editing ? 'Save item' : 'Add item'}</Button>
      </>}
    >
      <form id="item-form" onSubmit={submit} className="space-y-7">
        <section className="space-y-4">
          <h3 className="text-sm font-semibold">About the item</h3>
          <div className="flex items-center gap-4">
            {preview ? <img src={preview} alt="New picture" className="h-20 w-20 rounded-lg object-cover" />
              : <ItemThumb path={removePicture ? null : item?.image_path ?? null} name={form.name || 'Item'} className="h-20 w-20" />}
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border border-border-strong bg-surface px-3 text-sm font-medium hover:bg-surface-muted focus-within:outline-2 focus-within:outline-brand">
                  <ImagePlus aria-hidden className="h-4 w-4" />
                  {hasPicture ? 'Change picture' : 'Add picture'}
                  <input type="file" accept="image/*" className="sr-only" onChange={choosePicture} />
                </label>
                {hasPicture && <Button type="button" variant="ghost" size="sm" onClick={() => { setPicture(null); setRemovePicture(true) }}>Remove picture</Button>}
              </div>
              <p className="text-xs text-ink-muted">A JPEG, PNG or WebP photo. It is shrunk to a small thumbnail when saved.</p>
            </div>
          </div>
          <Field label="Name">
            <Input required value={form.name} onChange={(e) => set('name', e.target.value)} />
          </Field>
          {exact && (
            <div role="alert" className="rounded-xl border border-danger/20 border-l-4 border-l-danger bg-danger-soft px-3 py-2 text-sm text-danger">
              <p className="flex items-center gap-1 font-medium"><AlertTriangle className="h-4 w-4" aria-hidden /> This item already exists</p>
              <p className="mt-1">{exact.code} - {exact.name}{!exact.active && ' (inactive, make it active again from Settings, Item master)'}. Use the existing item instead of adding it again.</p>
            </div>
          )}
          {!exact && shownSimilar.length > 0 && (
            <div role="status" className="rounded-xl border border-warn/25 border-l-4 border-l-warn bg-warn-soft px-3 py-2 text-sm text-warn">
              <p className="flex items-center gap-1 font-medium"><AlertTriangle className="h-4 w-4" aria-hidden /> Similar items already exist</p>
              <ul className="mt-1 list-inside list-disc">{shownSimilar.map((s) => <li key={s.id}>{s.code} - {s.name}{!s.active && ' (inactive)'}</li>)}</ul>
              <p className="mt-1">Use the existing item instead of adding a duplicate.</p>
            </div>
          )}
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Category">
              <Select required value={form.category_id} onChange={(e) => set('category_id', e.target.value)}>
                <option value="">Select</option>
                {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
            <Field label="Unit of measure">
              <Select required value={form.unit_id} onChange={(e) => set('unit_id', e.target.value)}>
                <option value="">Select</option>
                {units.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </Select>
            </Field>
            <Field label="Preferred supplier">
              <Select value={form.supplier_id} onChange={(e) => set('supplier_id', e.target.value)}>
                <option value="">None</option>
                {suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            </Field>
            <fieldset className="sm:col-span-2">
              <legend className="mb-1 text-sm font-medium">Also bought from</legend>
              <p className="mb-2 text-xs text-ink-muted">Other suppliers this item can come from. A supplier is added here by itself the first time you receive the item from them.</p>
              <div className="flex flex-wrap gap-2">
                {suppliers.data?.filter((s) => String(s.id) !== form.supplier_id).map((s) => (
                  <label key={s.id} className={`cursor-pointer rounded-full border px-3 py-1 text-sm transition-colors ${otherSuppliers.includes(s.id) ? 'border-brand bg-brand-soft font-semibold text-brand-deep' : 'border-border hover:bg-surface-muted'}`}>
                    <input type="checkbox" className="sr-only" checked={otherSuppliers.includes(s.id)}
                      onChange={() => setOtherSuppliers((all) => (all.includes(s.id) ? all.filter((x) => x !== s.id) : [...all, s.id]))} /> {s.name}
                  </label>
                ))}
              </div>
            </fieldset>
            <Field label="Storage location"><Input value={form.storage_location} onChange={(e) => set('storage_location', e.target.value)} /></Field>
          </div>
        </section>

        <section className="space-y-4 border-t border-border pt-6">
          <h3 className="text-sm font-semibold">Cost and stock levels</h3>
          <div className="grid gap-5 sm:grid-cols-3">
            <Field label="Starting price"><Input type="number" step="0.001" min={0} value={form.unit_cost} onChange={(e) => set('unit_cost', e.target.value)} /></Field>
            <Field label="Minimum level"><Input type="number" min={0} value={form.min_level} onChange={(e) => set('min_level', e.target.value)} /></Field>
            <Field label="Target level"><Input type="number" min={0} value={form.target_level} onChange={(e) => set('target_level', e.target.value)} /></Field>
          </div>
        </section>

        {!editing && (
          <section className="space-y-4 border-t border-border pt-6">
            <h3 className="text-sm font-semibold">Opening stock</h3>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Quantity on hand"><Input type="number" min={0} value={form.opening_qty} onChange={(e) => set('opening_qty', e.target.value)} /></Field>
              <Field label="Counted at">
                <Select value={form.opening_location_id} onChange={(e) => set('opening_location_id', e.target.value)}>
                  {me?.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </Select>
              </Field>
            </div>
            <label className="flex items-center gap-2.5 text-sm"><input type="checkbox" checked={form.is_tracked_asset} onChange={(e) => set('is_tracked_asset', e.target.checked)} /> Track individual assets of this item</label>
          </section>
        )}
      </form>
    </Modal>
  )
}
