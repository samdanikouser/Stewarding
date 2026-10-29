import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDateTime, label } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { useLookup } from '@/lib/useLookups'
import type { EquipmentItem } from '@/pages/MonitoringRecordForm'

interface ActionRow {
  id: number
  reading_id: number
  action: string
  taken_by: number
  retest_due_at: string | null
  status: string
  equipment_id: number
  stage: string
  display: string
  recorded_at: string
  location_id: number
}

interface PanelProps {
  locationId: number | null
  equipment: EquipmentItem[]
  refreshKey: number
  onRetest: (equipmentId: number, readingId: number, stage: string) => void
  onChanged: () => void
}

type Dialog = { kind: 'action' | 'reject'; row: ActionRow } | null

export function CorrectiveActionsPanel({ locationId, equipment, refreshKey, onRetest, onChanged }: PanelProps) {
  const { me } = useAuth()
  const run = useRun()
  const can = (p: string) => me?.permissions.includes(p) ?? false
  const { data, reload } = useApi<ActionRow[]>(`/monitoring/corrective-actions${qs({ location_id: locationId, k: refreshKey })}`)
  const standardActions = useLookup('corrective_action')
  const [dialog, setDialog] = useState<Dialog>(null)
  const [text, setText] = useState('')
  const names = new Map(equipment.map((e) => [e.id, e.name]))
  const open = (data ?? []).filter((a) => a.status !== 'resolved')

  async function send(path: string, body: unknown, success: string) {
    const ok = await run(() => api(`/monitoring/corrective-actions/${path}`, { body }), success)
    if (ok) {
      setDialog(null)
      setText('')
      reload()
      onChanged()
    }
  }

  return (
    <Card className={open.length ? 'border-danger/50' : undefined}>
      <CardHeader className="p-6 pb-3"><CardTitle className="text-lg">Open corrective actions{open.length ? ` (${open.length})` : ''}</CardTitle></CardHeader>
      <CardContent className="p-6 pt-2">
        {open.length === 0 ? <EmptyState title="Nothing outstanding" /> : (
          <ul className="divide-y divide-border">
            {open.map((a) => (
              <li key={a.id} className="space-y-2 py-4 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{names.get(a.equipment_id)} - {label(a.stage)}: {a.display}</span>
                  <StatusBadge status={a.status} />
                </div>
                <p className="text-ink-muted">Recorded {fmtDateTime(a.recorded_at)}{a.action && ` - ${a.action}`}</p>
                {a.retest_due_at && a.status === 'retest_due' && <p className="text-warn">Retest due {fmtDateTime(a.retest_due_at)}</p>}
                <div className="flex flex-wrap gap-2">
                  {a.status === 'action_required' && can('temp.record') && (
                    <Button size="sm" onClick={() => setDialog({ kind: 'action', row: a })}>Record action</Button>
                  )}
                  {a.status === 'retest_due' && can('temp.record') && (
                    <Button size="sm" onClick={() => onRetest(a.equipment_id, a.reading_id, a.stage)}>Record retest</Button>
                  )}
                  {can('temp.review') && a.taken_by !== me?.id && a.status !== 'action_required' && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => send(`${a.id}/decision`, { decision: 'approve' }, 'Action approved')}>Approve</Button>
                      <Button size="sm" variant="danger" onClick={() => setDialog({ kind: 'reject', row: a })}>Reject</Button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <Modal
        open={dialog !== null}
        size="md"
        title={dialog?.kind === 'action' ? 'Record corrective action' : 'Reject corrective action'}
        description={dialog ? `${names.get(dialog.row.equipment_id)}, ${label(dialog.row.stage)}: ${dialog.row.display}` : undefined}
        onClose={() => setDialog(null)}
        footer={<>
          <Button variant="outline" onClick={() => setDialog(null)}>Cancel</Button>
          <Button disabled={text.trim().length < 5}
            onClick={() => dialog && (dialog.kind === 'action'
              ? send(`${dialog.row.id}/action`, { action: text }, 'Corrective action recorded - retest due')
              : send(`${dialog.row.id}/decision`, { decision: 'reject', note: text }, 'Action rejected'))}>
            Confirm
          </Button>
        </>}
      >
        <Field label={dialog?.kind === 'action' ? 'What was done?' : 'Why is it rejected?'}>
          <Input list={dialog?.kind === 'action' ? 'panel-standard-actions' : undefined} value={text} onChange={(e) => setText(e.target.value)} />
          <datalist id="panel-standard-actions">{standardActions.map((a) => <option key={a} value={a} />)}</datalist>
        </Field>
      </Modal>
    </Card>
  )
}
