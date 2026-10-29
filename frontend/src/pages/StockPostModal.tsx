import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { label } from '@/lib/format'
import { useRun } from '@/lib/toast'
import type { Item } from '@/lib/useItems'

interface PostModalProps {
  item: Item | null
  defaultLocation: number | null
  onClose: () => void
  onPosted: () => void
}

export function StockPostModal({ item, defaultLocation, onClose, onPosted }: PostModalProps) {
  const { me } = useAuth()
  const run = useRun()
  const canAdjust = me?.permissions.includes('stock.approve') ?? false
  const [type, setType] = useState('receipt')
  const [location, setLocation] = useState(defaultLocation ? String(defaultLocation) : String(me?.locations[0]?.id ?? ''))
  const [qty, setQty] = useState('')
  const [reason, setReason] = useState('')
  const needsReason = type === 'adjustment' || type === 'damage'

  async function submit() {
    const ok = await run(
      () => api('/inventory/transactions', { body: { item_id: item?.id, location_id: Number(location), txn_type: type, qty: Number(qty), reason: reason || null } }),
      'Stock updated',
    )
    if (ok) {
      setQty('')
      setReason('')
      onPosted()
    }
  }

  return (
    <Modal open={item !== null} title={item ? `Stock movement: ${item.name}` : ''} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Location">
          <Select value={location} onChange={(e) => setLocation(e.target.value)}>
            {me?.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </Select>
        </Field>
        <Field label="Type">
          <Select value={type} onChange={(e) => setType(e.target.value)}>
            {['receipt', 'issue', 'return', 'damage', ...(canAdjust ? ['adjustment'] : [])].map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </Select>
        </Field>
        <Field label={type === 'adjustment' ? 'Quantity (negative to reduce)' : 'Quantity'}>
          <Input type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
        </Field>
        <Field label={needsReason ? 'Reason (required)' : 'Reason (optional)'}>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!qty || Number(qty) === 0 || (needsReason && reason.trim().length < 5)} onClick={submit}>Post</Button>
        </div>
      </div>
    </Modal>
  )
}
