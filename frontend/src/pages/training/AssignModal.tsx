import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { iso } from '@/lib/dates'
import type { CourseRow } from '@/lib/training'
import { useRun, useToast } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'

interface Person { id: number; full_name: string; employee_code: string; job_title: string }
interface Role { id: number; label: string; users: number }

function toggle(set: Set<number>, id: number): Set<number> {
  const next = new Set(set)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

const BOX = 'max-h-56 space-y-1 overflow-y-auto rounded-xl border border-border bg-surface p-2'
const ROW = 'flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-surface-muted'

/** Gives a published course to chosen people, to everyone in a role, or to everyone at a location, with an optional due date. */
export function AssignModal({ course, onClose, onDone }: { course: CourseRow; onClose: () => void; onDone: () => void }) {
  const { me } = useAuth()
  const run = useRun()
  const toast = useToast()
  const people = useApi<{ items: Person[] }>(`/employees${qs({ status: 'active', size: 200 })}`)
  const roles = useApi<Role[]>('/roles')
  const [search, setSearch] = useState('')
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const [chosenRoles, setChosenRoles] = useState<Set<number>>(new Set())
  const [chosenPlaces, setChosenPlaces] = useState<Set<number>>(new Set())
  const [due, setDue] = useState('')
  const [today] = useState(() => iso(new Date()))

  const needle = search.trim().toLowerCase()
  const shown = (people.data?.items ?? []).filter((p) => !needle || `${p.full_name} ${p.employee_code} ${p.job_title}`.toLowerCase().includes(needle))
  const nothing = chosen.size + chosenRoles.size + chosenPlaces.size === 0

  async function save(event: FormEvent) {
    event.preventDefault()
    let outcome: { assigned: number; already_had_it: number; without_login: number } | null = null
    const ok = await run(async () => {
      outcome = await api(`/training/courses/${course.id}/assign`, {
        body: { employee_ids: [...chosen], role_ids: [...chosenRoles], location_ids: [...chosenPlaces], due_on: due || null },
      })
    })
    if (ok && outcome) {
      const { assigned, already_had_it: already, without_login: noLogin } = outcome
      toast('ok', `Assigned to ${assigned} ${assigned === 1 ? 'person' : 'people'}${already ? `, ${already} already had it` : ''}${noLogin ? `, ${noLogin} cannot sign in` : ''}`)
      onDone()
    }
  }

  return (
    <Modal open size="xl" title={`Assign "${course.title}"`} onClose={onClose}
      description="Choose people, or everyone in a role or at a location. Anyone who already has the course keeps their progress."
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="assign-form" disabled={nothing}>Assign course</Button>
      </>}>
      <form id="assign-form" onSubmit={save} className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-3">
          <section className="space-y-2" aria-label="People">
            <h3 className="text-sm font-semibold">People ({chosen.size} chosen)</h3>
            <Input aria-label="Search people" type="search" placeholder="Search name, code or job" value={search} onChange={(e) => setSearch(e.target.value)} />
            <div className={BOX}>
              {shown.map((p) => (
                <label key={p.id} className={ROW}>
                  <input type="checkbox" checked={chosen.has(p.id)} onChange={() => setChosen(toggle(chosen, p.id))} />
                  <span className="min-w-0"><span className="block truncate">{p.full_name}</span><span className="block truncate text-xs text-ink-muted">{p.job_title}</span></span>
                </label>
              ))}
              {people.data && shown.length === 0 && <p className="p-2 text-sm text-ink-muted">Nobody matches.</p>}
            </div>
          </section>
          <section className="space-y-2" aria-label="Roles">
            <h3 className="text-sm font-semibold">Everyone in a role ({chosenRoles.size})</h3>
            <div className={BOX}>
              {(roles.data ?? []).map((r) => (
                <label key={r.id} className={ROW}>
                  <input type="checkbox" checked={chosenRoles.has(r.id)} onChange={() => setChosenRoles(toggle(chosenRoles, r.id))} />
                  <span>{r.label} <span className="text-xs text-ink-muted">({r.users})</span></span>
                </label>
              ))}
            </div>
          </section>
          <section className="space-y-2" aria-label="Locations">
            <h3 className="text-sm font-semibold">Everyone at a location ({chosenPlaces.size})</h3>
            <div className={BOX}>
              {(me?.locations ?? []).map((l) => (
                <label key={l.id} className={ROW}>
                  <input type="checkbox" checked={chosenPlaces.has(l.id)} onChange={() => setChosenPlaces(toggle(chosenPlaces, l.id))} />
                  <span>{l.name}</span>
                </label>
              ))}
            </div>
          </section>
        </div>
        <div className="max-w-xs">
          <Field label="Due date (optional)"><Input type="date" min={today} value={due} onChange={(e) => setDue(e.target.value)} /></Field>
        </div>
      </form>
    </Modal>
  )
}
