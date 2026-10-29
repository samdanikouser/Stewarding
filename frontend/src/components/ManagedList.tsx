import { Check, Pencil, Plus, Power, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export interface ManagedEntry {
  id: number
  name: string
  active: boolean
}

interface ManagedListProps {
  entries: ManagedEntry[]
  placeholder: string
  noun: string
  onAdd: (name: string) => Promise<boolean>
  onRename: (id: number, name: string) => Promise<boolean>
  onToggle: (id: number, active: boolean) => Promise<boolean>
  onDelete: (id: number) => Promise<boolean>
}

/** Add, rename, switch off and delete the values of a list; a value that records already use is refused with the reason. */
export function ManagedList({ entries, placeholder, noun, onAdd, onRename, onToggle, onDelete }: ManagedListProps) {
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState<number | null>(null)
  const [text, setText] = useState('')
  const [removing, setRemoving] = useState<ManagedEntry | null>(null)

  async function add() {
    if (draft.trim().length >= 2 && (await onAdd(draft))) setDraft('')
  }

  async function save(id: number) {
    if (await onRename(id, text)) setEditing(null)
  }

  async function remove() {
    if (!removing) return
    await onDelete(removing.id)
    setRemoving(null)
  }

  return (
    <div className="space-y-4">
      <form className="flex gap-3" onSubmit={(e) => { e.preventDefault(); add() }}>
        <Input aria-label={placeholder} placeholder={placeholder} value={draft} onChange={(e) => setDraft(e.target.value)} />
        <Button type="submit" disabled={draft.trim().length < 2}><Plus className="h-4 w-4" /> Add</Button>
      </form>
      {entries.length === 0 ? <p className="py-4 text-center text-sm text-ink-muted">Nothing here yet.</p> : (
        <ul className="space-y-2">
          {entries.map((e) => (
            <li key={e.id} className={cn('flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border px-4 py-3 text-sm', !e.active && 'bg-surface-muted text-ink-muted')}>
              {editing === e.id ? (
                <Input aria-label={`Rename ${e.name}`} autoFocus className="max-w-xs" value={text} onChange={(ev) => setText(ev.target.value)}
                  onKeyDown={(ev) => { if (ev.key === 'Enter') save(e.id); if (ev.key === 'Escape') setEditing(null) }} />
              ) : (
                <span className="flex items-center gap-2 font-medium">{e.name}{!e.active && <Badge>Inactive</Badge>}</span>
              )}
              <span className="flex shrink-0 flex-wrap gap-2">
                {editing === e.id ? (
                  <>
                    <Button size="sm" variant="outline" onClick={() => save(e.id)}><Check className="h-3.5 w-3.5" /> Save</Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(null)}><X className="h-3.5 w-3.5" /> Cancel</Button>
                  </>
                ) : (
                  <>
                    <Button size="sm" variant="outline" aria-label={`Rename ${e.name}`} onClick={() => { setEditing(e.id); setText(e.name) }}><Pencil className="h-3.5 w-3.5" /> Rename</Button>
                    <Button size="sm" variant="outline" aria-label={`${e.active ? 'Make inactive' : 'Make active'} ${e.name}`} onClick={() => onToggle(e.id, !e.active)}><Power className="h-3.5 w-3.5" /> {e.active ? 'Make inactive' : 'Make active'}</Button>
                    <Button size="sm" variant="outline" aria-label={`Delete ${e.name}`} className="border-danger/40 text-danger hover:bg-danger-soft" onClick={() => setRemoving(e)}><Trash2 className="h-3.5 w-3.5" /> Delete</Button>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog open={removing !== null} title={`Delete ${noun}`} confirmLabel={`Delete ${noun}`}
        message={`Delete ${removing?.name ?? `this ${noun}`}? This cannot be undone. One that records already use cannot be deleted; make it inactive instead.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
