import { qs, useApi } from '@/lib/useApi'

interface Asset {
  id: number
  asset_tag: string
  condition: string
}

interface Props {
  itemId: number
  locationId: number
  qty: number
  value: number[]
  onChange: (ids: number[]) => void
}

/** The asset tags of an item at a location, to tick the ones that are moving; no more than `qty` can be ticked. */
export function AssetTagPicker({ itemId, locationId, qty, value, onChange }: Props) {
  const assets = useApi<Asset[]>(`/inventory/assets${qs({ item_id: itemId, location_id: locationId })}`)
  const full = value.length >= qty
  const toggle = (id: number) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])

  return (
    <fieldset className="w-full space-y-2 rounded-lg bg-surface-muted/60 p-3">
      <legend className="px-1 text-xs font-medium text-ink-muted">Asset tags moving ({value.length} of {qty} chosen)</legend>
      {assets.data?.length === 0 && <p className="text-sm text-danger">No asset tags are recorded for this item here.</p>}
      <div className="flex flex-wrap gap-2">
        {assets.data?.map((a) => (
          <label key={a.id} className={`inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-full border px-3 text-sm ${value.includes(a.id) ? 'border-brand bg-brand-soft font-semibold text-brand-deep' : 'border-border bg-surface'} ${!value.includes(a.id) && full ? 'cursor-not-allowed opacity-50' : ''}`}>
            <input type="checkbox" className="sr-only" checked={value.includes(a.id)} disabled={!value.includes(a.id) && full} onChange={() => toggle(a.id)} />
            {a.asset_tag}{a.condition !== 'good' && <span className="text-xs text-ink-muted"> ({a.condition})</span>}
          </label>
        ))}
      </div>
    </fieldset>
  )
}
