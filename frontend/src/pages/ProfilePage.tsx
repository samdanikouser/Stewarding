import { useEffect, useState, type FormEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { StatusBadge } from '@/components/ui/status-badge'
import { Skeleton } from '@/components/ui/table'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { api, tokenStore } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { fmtDate, fmtDateTime, initials } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { PasswordForm } from '@/pages/ChangePasswordPage'

interface Employee {
  code: string
  full_name: string
  job_title: string
  company: string | null
  status: string
  phone: string | null
  emergency_contact: string | null
  date_joined: string | null
  supervisor: string | null
  locations: string[]
}

interface Profile {
  email: string
  role_label: string
  last_login_at: string | null
  employee: Employee | null
}

function Fact({ label, children }: { label: string; children: string | null }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-sm">{children || '-'}</dd>
    </div>
  )
}

function DetailsCard({ employee, onSaved }: { employee: Employee; onSaved: () => void }) {
  const run = useRun()
  const [phone, setPhone] = useState(employee.phone ?? '')
  const [contact, setContact] = useState(employee.emergency_contact ?? '')
  const changed = phone !== (employee.phone ?? '') || contact !== (employee.emergency_contact ?? '')

  async function save(event: FormEvent) {
    event.preventDefault()
    const body = { phone: phone.trim() || null, emergency_contact: contact.trim() || null }
    if (await run(() => api('/profile', { method: 'PUT', body }), 'Profile saved')) onSaved()
  }

  return (
    <Card>
      <CardHeader><CardTitle>Details</CardTitle></CardHeader>
      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Fact label="Job title">{employee.job_title}</Fact>
          <Fact label="Company">{employee.company}</Fact>
          <Fact label="Supervisor">{employee.supervisor}</Fact>
          <Fact label="Joined">{employee.date_joined ? fmtDate(employee.date_joined) : null}</Fact>
          <div className="sm:col-span-2">
            <dt className="text-xs text-ink-muted">Locations</dt>
            <dd className="mt-1 flex flex-wrap gap-2">
              {employee.locations.map((name) => <Badge key={name}>{name}</Badge>)}
            </dd>
          </div>
        </dl>
        <form onSubmit={save} className="mt-5 space-y-4 border-t border-border pt-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Phone">
              <Input type="tel" autoComplete="tel" maxLength={40} value={phone} onChange={(e) => setPhone(e.target.value)} />
            </Field>
            <Field label="Emergency contact">
              <Input maxLength={200} value={contact} onChange={(e) => setContact(e.target.value)} />
            </Field>
          </div>
          <Button type="submit" disabled={!changed}>Save changes</Button>
        </form>
      </CardContent>
    </Card>
  )
}

export function ProfilePage() {
  const { me, logout } = useAuth()
  const { data, reload } = useApi<Profile>('/profile')
  const { hash } = useLocation()
  const run = useRun()
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    if (data && hash === '#security') document.getElementById('security')?.scrollIntoView()
  }, [data, hash])

  async function signOutOthers() {
    const done = await run(async () => {
      const { access_token } = await api<{ access_token: string }>('/auth/sign-out-others', { method: 'POST' })
      tokenStore.set(access_token)
    }, 'Signed out of your other devices')
    if (done) setConfirming(false)
  }

  if (!data || !me) return <Skeleton className="h-64 w-full" />
  const employee = data.employee
  const name = employee?.full_name ?? data.email
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">My profile</h1>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-5 pt-6">
          <span aria-hidden className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-brand text-xl font-semibold text-brand-ink">{initials(name)}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xl font-semibold">{name}</span>
              <Badge>{data.role_label}</Badge>
              {employee && <StatusBadge status={employee.status} />}
            </div>
            <p className="mt-1 break-words text-sm text-ink-muted">
              {[employee ? data.email : null, employee?.code, data.last_login_at ? `Last sign-in ${fmtDateTime(data.last_login_at)}` : null].filter(Boolean).join(' · ')}
            </p>
          </div>
          <Button variant="outline" onClick={logout}>Sign out</Button>
        </CardContent>
      </Card>

      <div className="grid items-start gap-4 xl:grid-cols-[3fr_2fr]">
        {employee && <DetailsCard key={`${employee.phone}|${employee.emergency_contact}`} employee={employee} onSaved={reload} />}
        <div className="space-y-4">
          <Card id="security">
            <CardHeader><CardTitle>Security</CardTitle></CardHeader>
            <CardContent>
              <PasswordForm />
              <div className="mt-5 border-t border-border pt-5">
                <Button variant="outline" onClick={() => setConfirming(true)}>Sign out other devices</Button>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>My access</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {me.modules.map((m) => <Badge key={m.key}>{m.label}</Badge>)}
            </CardContent>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={confirming} title="Sign out other devices" confirmLabel="Sign them out" message="Every other phone or computer signed in as you will have to sign in again. This device stays signed in."
        onConfirm={signOutOthers} onCancel={() => setConfirming(false)} />
    </div>
  )
}
