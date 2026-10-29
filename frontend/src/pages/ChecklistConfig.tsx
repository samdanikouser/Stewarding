import { Pencil, Plus, Power, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { LocationSelect } from '@/components/LocationSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { EmptyState } from '@/components/ui/table'
import { api } from '@/lib/api'
import { label } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { useLookup } from '@/lib/useLookups'
import { ChecklistTaskModal, type ConfigTask } from '@/pages/ChecklistTaskModal'

interface Template {
  id: number
  name: string
  category: string
  frequency: string
  active: boolean
  tasks: ConfigTask[]
}

interface TemplateDraft {
  id: number | null
  name: string
  category: string
  frequency: string
}

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const daysOf = (weekdays: string) => (weekdays.split(',').length === 7 ? 'Every day' : weekdays.split(',').map((d) => DAY_NAMES[Number(d)]).join(', '))
const DANGER = 'border-danger/40 text-danger hover:bg-danger-soft'

interface ConfigProps {
  locationId: number | null
  onLocation: (id: number | null) => void
}

export function ChecklistConfig({ locationId, onLocation }: ConfigProps) {
  const run = useRun()
  const { data, reload } = useApi<Template[]>(locationId ? `/checklists/templates${qs({ location_id: locationId })}` : null)
  const categories = useLookup('checklist_category')
  const [template, setTemplate] = useState<TemplateDraft | null>(null)
  const [editing, setEditing] = useState<{ templateId: number; frequency: string; task: ConfigTask | null } | null>(null)
  const [removingTask, setRemovingTask] = useState<ConfigTask | null>(null)
  const [removingTemplate, setRemovingTemplate] = useState<Template | null>(null)

  async function saveTemplate(event: FormEvent) {
    event.preventDefault()
    if (!template) return
    const body = { name: template.name, category: template.category || categories[0] || 'General', frequency: template.frequency }
    const ok = await run(
      () => template.id ? api(`/checklists/templates/${template.id}`, { method: 'PUT', body }) : api('/checklists/templates', { body: { ...body, location_id: locationId } }),
      template.id ? 'Checklist updated' : 'Checklist added',
    )
    if (ok) {
      setTemplate(null)
      reload()
    }
  }

  async function setTemplateActive(t: Template) {
    if (await run(() => api(`/checklists/templates/${t.id}`, { method: 'PUT', body: { active: !t.active } }), t.active ? 'Checklist made inactive' : 'Checklist made active')) reload()
  }

  async function setTaskActive(task: ConfigTask) {
    const { id: _id, ...rest } = task
    if (await run(() => api(`/checklists/tasks/${task.id}`, { method: 'PUT', body: { ...rest, active: !task.active } }), task.active ? 'Task made inactive' : 'Task made active')) reload()
  }

  async function removeTask() {
    if (!removingTask) return
    const ok = await run(() => api(`/checklists/tasks/${removingTask.id}/remove`, { method: 'POST' }), 'Task deleted')
    setRemovingTask(null)
    if (ok) reload()
  }

  async function removeTemplate() {
    if (!removingTemplate) return
    const ok = await run(() => api(`/checklists/templates/${removingTemplate.id}`, { method: 'DELETE' }), 'Checklist deleted')
    setRemovingTemplate(null)
    if (ok) reload()
  }

  async function applyStarter() {
    const ok = await run(() => api('/checklists/starter', { body: { location_id: locationId } }), 'Starter templates applied')
    if (ok) reload()
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <LocationSelect value={locationId} onChange={onLocation} />
        <div className="flex flex-wrap gap-3">
          <Button variant="outline" disabled={!locationId} onClick={applyStarter}>Apply starter templates</Button>
          <Button disabled={!locationId} onClick={() => setTemplate({ id: null, name: '', category: categories[0] ?? 'General', frequency: 'daily' })}><Plus className="h-4 w-4" /> Add checklist</Button>
        </div>
      </div>

      {data?.length === 0 && <EmptyState title="No checklists at this location" />}
      {data?.map((t) => (
        <Card key={t.id} className={t.active ? undefined : 'bg-surface-muted/60'}>
          <CardHeader className="flex-col gap-3 p-6 pb-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1.5">
              <CardTitle className="flex flex-wrap items-center gap-2 text-lg">{t.name}</CardTitle>
              <div className="flex flex-wrap gap-1.5">
                <Badge>{label(t.frequency)}</Badge>
                <Badge>{t.category}</Badge>
                {!t.active && <Badge tone="warn">Inactive</Badge>}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setTemplate({ id: t.id, name: t.name, category: t.category, frequency: t.frequency })}><Pencil className="h-3.5 w-3.5" /> Edit</Button>
              <Button size="sm" variant="outline" onClick={() => setTemplateActive(t)}><Power className="h-3.5 w-3.5" /> {t.active ? 'Make inactive' : 'Make active'}</Button>
              <Button size="sm" variant="outline" className={DANGER} onClick={() => setRemovingTemplate(t)}><Trash2 className="h-3.5 w-3.5" /> Delete</Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4 p-6 pt-3">
            {t.tasks.length === 0 ? <p className="text-sm text-ink-muted">No tasks yet.</p> : (
              <ul className="divide-y divide-border rounded-xl border border-border">
                {t.tasks.map((task) => (
                  <li key={task.id} className={`flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm ${task.active ? '' : 'bg-surface-muted/60 text-ink-muted'}`}>
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{task.description}</span>
                      <span className="text-xs text-ink-muted">{daysOf(task.weekdays)}{task.scheduled_time ? ` from ${task.scheduled_time.slice(0, 5)}` : ''}{task.deadline_time ? `, due by ${task.deadline_time.slice(0, 5)}` : ''}</span>
                    </span>
                    <span className="flex flex-wrap items-center gap-1.5">
                      {task.requires_verification && <Badge tone="warn">Verify</Badge>}
                      {task.requires_photo && <Badge>Photo</Badge>}
                      {task.requires_reading && <Badge>Reading</Badge>}
                      {!task.active && <Badge>Inactive</Badge>}
                      <Button size="sm" variant="outline" onClick={() => setEditing({ templateId: t.id, frequency: t.frequency, task })}><Pencil className="h-3.5 w-3.5" /> Edit</Button>
                      <Button size="sm" variant="outline" onClick={() => setTaskActive(task)}><Power className="h-3.5 w-3.5" /> {task.active ? 'Make inactive' : 'Make active'}</Button>
                      <Button size="sm" variant="outline" className={DANGER} onClick={() => setRemovingTask(task)}><Trash2 className="h-3.5 w-3.5" /> Delete</Button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <Button size="sm" variant="outline" onClick={() => setEditing({ templateId: t.id, frequency: t.frequency, task: null })}><Plus className="h-3.5 w-3.5" /> Add task</Button>
          </CardContent>
        </Card>
      ))}

      {editing && <ChecklistTaskModal templateId={editing.templateId} templateFrequency={editing.frequency} task={editing.task} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload() }} />}

      <Modal
        open={template !== null}
        size="md"
        title={template?.id ? 'Edit checklist' : 'Add checklist'}
        description="A named set of tasks that repeats on its own schedule."
        onClose={() => setTemplate(null)}
        footer={<>
          <Button type="button" variant="outline" onClick={() => setTemplate(null)}>Cancel</Button>
          <Button type="submit" form="template-form">Save checklist</Button>
        </>}
      >
        {template && (
          <form id="template-form" onSubmit={saveTemplate} className="space-y-5">
            <Field label="Name"><Input required minLength={2} maxLength={120} value={template.name} onChange={(e) => setTemplate({ ...template, name: e.target.value })} /></Field>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Category">
                <Select value={template.category} onChange={(e) => setTemplate({ ...template, category: e.target.value })}>
                  {[...new Set([...categories, template.category])].map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </Field>
              <Field label="Frequency">
                <Select value={template.frequency} onChange={(e) => setTemplate({ ...template, frequency: e.target.value })}>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="per_shift">Once per shift</option>
                  <option value="custom">Custom</option>
                </Select>
              </Field>
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDialog open={removingTask !== null} title="Delete task" confirmLabel="Delete task"
        message={`Delete "${removingTask?.description}"? A task that has records cannot be deleted; make it inactive instead and past records are kept.`}
        onConfirm={removeTask} onCancel={() => setRemovingTask(null)} />
      <ConfirmDialog open={removingTemplate !== null} title="Delete checklist" confirmLabel="Delete checklist"
        message={`Delete ${removingTemplate?.name ?? 'this checklist'} and its tasks? This cannot be undone. A checklist that has records cannot be deleted; make it inactive instead.`}
        onConfirm={removeTemplate} onCancel={() => setRemovingTemplate(null)} />
    </div>
  )
}
