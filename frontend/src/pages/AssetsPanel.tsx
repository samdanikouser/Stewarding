import { Select } from '@/components/ui/select'
import { EmptyState, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import type { Item } from '@/lib/useItems'

interface Asset {
  id: number
  item_id: number
  asset_tag: string
  location_id: number
  condition: string
}

export function AssetsPanel({ locationId, items }: { locationId: number | null; items: Item[] }) {
  const { me } = useAuth()
  const run = useRun()
  const canEdit = me?.permissions.includes('inventory.count') ?? false
  const { data, reload } = useApi<Asset[]>(`/inventory/assets${qs({ location_id: locationId })}`)
  const names = new Map(items.map((i) => [i.id, i.name]))
  const locations = new Map(me?.locations.map((l) => [l.id, l.name]))

  async function setCondition(asset: Asset, condition: string) {
    if (await run(() => api(`/inventory/assets/${asset.id}`, { method: 'PUT', body: { condition } }), 'Condition updated')) reload()
  }

  if (data?.length === 0) return <EmptyState title="No tracked assets here" />
  return (
    <Table>
      <thead><tr><Th>Tag</Th><Th>Item</Th><Th>Location</Th><Th>Condition</Th></tr></thead>
      <tbody>
        {data?.map((a) => (
          <tr key={a.id}>
            <Td className="font-medium">{a.asset_tag}</Td>
            <Td>{names.get(a.item_id)}</Td>
            <Td>{locations.get(a.location_id)}</Td>
            <Td>
              {canEdit ? (
                <Select aria-label={`Condition of ${a.asset_tag}`} className="w-auto" value={a.condition} onChange={(e) => setCondition(a, e.target.value)}>
                  {['good', 'fair', 'damaged', 'missing'].map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              ) : a.condition}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  )
}
