import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { PasswordInput } from '@/components/ui/password-input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { useLookup } from '@/lib/useLookups'

export interface EmployeeRow {
  id: number
  employee_code: string
  full_name: string
  job_title: string
  company?: string | null
  status: string
  face_enrolled?: boolean
  supervisor_id: number | null
  location_ids: number[]
  role: string | null
  role_tier?: string | null
  phone?: string | null
  email?: string | null
  emergency_contact?: string | null
  date_joined?: string | null
  account?: { change_required: boolean; last_login_at: string | null } | null
}

interface EmployeeFormProps {
  open: boolean
  employee: EmployeeRow | null
  supervisors: EmployeeRow[]
  onClose: () => void
  onSaved: () => void
}

export function EmployeeForm({ open, employee, supervisors, onClose, onSaved }: EmployeeFormProps) {
  const { me } = useAuth()
  const run = useRun()
  const titles = useLookup('job_title')
  const roles = useApi<{ name: string; label: string }[]>('/roles/options')
  const editing = employee !== null
  const [form, setForm] = useState({
    employee_code: employee?.employee_code ?? '',
    full_name: employee?.full_name ?? '',
    job_title: employee?.job_title ?? 'Steward',
    company: employee?.company ?? '',
    email: employee?.email ?? '',
    password: '',
    role: employee?.role ?? 'steward',
    phone: employee?.phone ?? '',
    emergency_contact: employee?.emergency_contact ?? '',
    date_joined: employee?.date_joined ?? '',
    supervisor_id: employee?.supervisor_id ? String(employee.supervisor_id) : '',
    location_ids: employee?.location_ids ?? [],
  })
  const [busy, setBusy] = useState(false)
  const set = (key: keyof typeof form, value: string | number[]) => setForm((f) => ({ ...f, [key]: value }))

  function toggleLocation(id: number) {
    set('location_ids', form.location_ids.includes(id) ? form.location_ids.filter((i) => i !== id) : [...form.location_ids, id])
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    const common = {
      full_name: form.full_name,
      job_title: form.job_title,
      company: form.company || null,
      role: form.role,
      ...(editing ? { email: form.email } : {}),
      phone: form.phone || null,
      emergency_contact: form.emergency_contact || null,
      date_joined: form.date_joined || null,
      supervisor_id: form.supervisor_id ? Number(form.supervisor_id) : null,
      location_ids: form.location_ids,
    }
    const ok = await run(
      () =>
        editing
          ? api(`/employees/${employee.id}`, { method: 'PUT', body: common })
          : api('/employees', { body: { ...common, employee_code: form.employee_code.trim() || undefined, email: form.email, password: form.password } }),
      editing ? 'Employee updated' : 'Employee created',
    )
    setBusy(false)
    if (ok) onSaved()
  }

  return (
    <Modal
      open={open}
      size="lg"
      title={editing ? 'Edit employee' : 'Add employee'}
      description={editing ? `${employee.employee_code} - ${employee.full_name}` : 'They sign in with the email and the password you set here.'}
      onClose={onClose}
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="employee-form" disabled={busy}>{busy ? 'Saving...' : editing ? 'Save employee' : 'Add employee'}</Button>
      </>}
    >
      <form id="employee-form" onSubmit={submit} className="space-y-7">
        <section className="space-y-4">
          <h3 className="text-sm font-semibold">Sign-in and role</h3>
          <div className="grid gap-5 sm:grid-cols-2">
            {!editing && (
              <Field label="Employee ID (leave empty to generate)">
                <Input value={form.employee_code} onChange={(e) => set('employee_code', e.target.value)} />
              </Field>
            )}
            <Field label={editing ? 'Email (their sign-in)' : 'Email'}>
              <Input required type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
            </Field>
            <Field label="Role">
              <Select value={form.role} onChange={(e) => set('role', e.target.value)}>
                {roles.data?.map((r) => <option key={r.name} value={r.name}>{r.label}</option>)}
              </Select>
            </Field>
            {!editing && (
              <Field label="Initial password">
                <PasswordInput required minLength={10} autoComplete="new-password" value={form.password} onChange={(e) => set('password', e.target.value)} />
              </Field>
            )}
          </div>
        </section>

        <section className="space-y-4 border-t border-border pt-6">
          <h3 className="text-sm font-semibold">About them</h3>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Full name">
              <Input required value={form.full_name} onChange={(e) => set('full_name', e.target.value)} />
            </Field>
            <Field label="Job title">
              <Input required list="job-titles" value={form.job_title} onChange={(e) => set('job_title', e.target.value)} />
              <datalist id="job-titles">{titles.map((t) => <option key={t} value={t} />)}</datalist>
            </Field>
            <Field label="Organization or company">
              <Input maxLength={120} value={form.company} onChange={(e) => set('company', e.target.value)} />
            </Field>
            <Field label="Date of joining">
              <Input type="date" value={form.date_joined} onChange={(e) => set('date_joined', e.target.value)} />
            </Field>
            <Field label="Phone">
              <Input type="tel" value={form.phone} onChange={(e) => set('phone', e.target.value)} />
            </Field>
            <Field label="Emergency contact">
              <Input value={form.emergency_contact} onChange={(e) => set('emergency_contact', e.target.value)} />
            </Field>
          </div>
        </section>

        <section className="space-y-4 border-t border-border pt-6">
          <h3 className="text-sm font-semibold">Where they work</h3>
          <Field label="Supervisor">
            <Select value={form.supervisor_id} onChange={(e) => set('supervisor_id', e.target.value)}>
              <option value="">None</option>
              {supervisors.filter((s) => s.id !== employee?.id).map((s) => (
                <option key={s.id} value={s.id}>{s.full_name}</option>
              ))}
            </Select>
          </Field>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Locations they can work at (optional)</legend>
            <p className="mb-2 text-sm text-ink-muted">Leave all unticked for every location. Which location they work at each day can be set in the Shift &amp; Duty Roster.</p>
            <div className="flex flex-wrap gap-2">
              {me?.locations.map((location) => (
                <label key={location.id} className={`cursor-pointer rounded-full border px-4 py-1.5 text-sm transition-colors ${form.location_ids.includes(location.id) ? 'border-brand bg-brand-soft font-semibold text-brand-deep' : 'border-border hover:bg-surface-muted'}`}>
                  <input type="checkbox" className="sr-only" checked={form.location_ids.includes(location.id)} onChange={() => toggleLocation(location.id)} /> {location.name}
                </label>
              ))}
            </div>
          </fieldset>
        </section>
      </form>
    </Modal>
  )
}
