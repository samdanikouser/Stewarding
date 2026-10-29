import { ArrowDown, ArrowUp, KeyRound, Pencil, Plus, Power, ScanFace, Search, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { ActionMenu } from '@/components/ui/action-menu'
import { FaceCapture, type FaceResult } from '@/components/FaceCapture'
import { Modal } from '@/components/ui/modal'
import { LocationSelect } from '@/components/LocationSelect'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { Select } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { EmptyState, Skeleton, SkeletonRows, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { Badge } from '@/components/ui/badge'
import { fmtDate, fmtDateTime } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'
import { EmployeeForm, type EmployeeRow } from '@/pages/EmployeeForm'
import { ResetPasswordModal } from '@/pages/ResetPasswordModal'
import { useToast } from '@/lib/toast'

interface Listing {
  total: number
  items: EmployeeRow[]
}

const SIZE = 15
const initials = (name: string) => name.split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
const COLUMNS = [
  ['employee_code', 'ID'],
  ['full_name', 'Name'],
  ['job_title', 'Job title'],
  ['status', 'Status'],
] as const

export function EmployeesPage() {
  const { me } = useAuth()
  const run = useRun()
  const canManage = me?.permissions.includes('employee.manage') ?? false
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [locationId, setLocationId] = useState<number | null>(null)
  const [sort, setSort] = useState('full_name')
  const [dir, setDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<EmployeeRow | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [toggling, setToggling] = useState<EmployeeRow | null>(null)
  const [removing, setRemoving] = useState<EmployeeRow | null>(null)
  const [resetting, setResetting] = useState<EmployeeRow | null>(null)
  const [enrolling, setEnrolling] = useState<EmployeeRow | null>(null)
  const toast = useToast()

  const { data, loading, reload } = useApi<Listing>(
    `/employees${qs({ search, status, location_id: locationId, sort, dir, page, size: SIZE })}`,
  )
  async function enroll(template: number[]): Promise<FaceResult> {
    try {
      await api(`/employees/${enrolling?.id}/face`, { body: { descriptor: template } })
      toast('ok', 'Face enrolled')
      setTimeout(() => { setEnrolling(null); reload() }, 1200)
      return { ok: true, message: 'Face enrolled' }
    } catch (err) {
      return { ok: false, message: err instanceof Error ? err.message : 'Could not save the face' }
    }
  }

  async function removeFace() {
    if (enrolling && await run(() => api(`/employees/${enrolling.id}/face`, { method: 'DELETE' }), 'Face removed')) {
      setEnrolling(null)
      reload()
    }
  }

  const { data: all } = useApi<Listing>(canManage ? '/employees?size=200' : null)
  const locationNames = new Map(me?.locations.map((l) => [l.id, l.code]))

  function sortBy(column: string) {
    setDir(sort === column && dir === 'asc' ? 'desc' : 'asc')
    setSort(column)
    setPage(1)
  }

  async function confirmToggle() {
    if (!toggling) return
    const action = toggling.status === 'active' ? 'deactivate' : 'activate'
    const ok = await run(() => api(`/employees/${toggling.id}/${action}`, { method: 'POST' }), `Employee ${action}d`)
    setToggling(null)
    if (ok) reload()
  }


  async function confirmRemove() {
    if (!removing) return
    const done = await run(() => api(`/employees/${removing.id}`, { method: 'DELETE' }), 'Employee deleted')
    setRemoving(null)
    if (done) reload()
  }

  const rowActions = (e: EmployeeRow) => (
    <>
      <Button size="sm" variant="outline" onClick={() => { setEditing(e); setFormOpen(true) }}><Pencil className="h-3.5 w-3.5" /> Edit</Button>
      <ActionMenu
        text="More"
        label={`More actions for ${e.full_name}`}
        actions={[
          { label: e.face_enrolled ? 'Update face' : 'Enroll face', icon: ScanFace, onClick: () => setEnrolling(e) },
          { label: 'Reset password', icon: KeyRound, onClick: () => setResetting(e), hidden: e.id === me?.employee?.id },
          { label: e.status === 'active' ? 'Deactivate' : 'Activate', icon: Power, onClick: () => setToggling(e) },
          { label: 'Delete employee', icon: Trash2, tone: 'danger', onClick: () => setRemoving(e), hidden: e.id === me?.employee?.id },
        ]}
      />
    </>
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Employees</h1>
        {canManage && (
          <Button onClick={() => { setEditing(null); setFormOpen(true) }}>
            <Plus className="h-4 w-4" /> Add employee
          </Button>
        )}
      </div>

      <div className="filter-bar">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink-muted" aria-hidden />
          <Input aria-label="Search employees" className="pl-9" placeholder="Search name or ID" value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        </div>
        <Select aria-label="Status" className="w-auto" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="pending">Pending approval</option>
          <option value="inactive">Inactive</option>
        </Select>
        <LocationSelect allowAll value={locationId} onChange={(id) => { setLocationId(id); setPage(1) }} />
        <Select aria-label="Sort by" className="w-auto xl:hidden" value={sort} onChange={(e) => sortBy(e.target.value)}>
          {COLUMNS.map(([key, text]) => <option key={key} value={key}>Sort by {text.toLowerCase()}</option>)}
        </Select>
      </div>

      <ul className="space-y-4 xl:hidden">
        {loading && !data ? <li><Skeleton className="h-28 w-full" /></li> : data?.items.map((e) => (
          <li key={e.id} className="space-y-4 rounded-2xl border border-border bg-surface p-5">
            <div className="flex items-start justify-between gap-3">
              <span className="flex min-w-0 items-center gap-3">
                <span aria-hidden className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-soft text-sm font-semibold text-brand">{initials(e.full_name)}</span>
                <span className="min-w-0">
                  <span className="block truncate text-base font-semibold">{e.full_name}</span>
                  <span className="text-sm text-ink-muted">{e.employee_code}</span>
                </span>
              </span>
              <StatusBadge status={e.status} />
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div><dt className="text-xs text-ink-muted">Job title</dt><dd>{e.job_title}{e.company && <span className="block text-xs text-ink-muted">{e.company}</span>}</dd></div>
              <div><dt className="text-xs text-ink-muted">Locations</dt><dd>{e.location_ids.map((id) => locationNames.get(id) ?? id).join(', ')}</dd></div>
              {canManage && <div><dt className="text-xs text-ink-muted">Joined</dt><dd>{fmtDate(e.date_joined)}</dd></div>}
              {canManage && <div><dt className="text-xs text-ink-muted">Last sign-in</dt><dd>{e.account?.change_required ? <Badge tone="warn">Temporary password</Badge> : e.account?.last_login_at ? fmtDateTime(e.account.last_login_at) : 'Never'}</dd></div>}
            </dl>
            {canManage && <div className="flex items-center gap-2 border-t border-border pt-4">{rowActions(e)}</div>}
          </li>
        ))}
      </ul>
      <div className="hidden xl:block">
        <Table>
          <thead>
            <tr>
              {([['full_name', 'Employee'], ['job_title', 'Job title'], ['status', 'Status']] as const).map(([key, text]) => (
                <Th key={key} aria-sort={sort === key ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                  <button type="button" className="inline-flex items-center gap-1" onClick={() => sortBy(key)}>
                    {text}
                    {sort === key && (dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                  </button>
                </Th>
              ))}
              <Th>Locations</Th>
              {canManage && <Th>Last sign-in</Th>}
              {canManage && <Th className="w-px text-right"><span className="sr-only">Actions</span></Th>}
            </tr>
          </thead>
          <tbody>
            {loading && !data ? <SkeletonRows cols={canManage ? 6 : 4} /> : data?.items.map((e) => (
              <tr key={e.id}>
                <Td className="py-4">
                  <span className="flex items-center gap-3">
                    <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">{initials(e.full_name)}</span>
                    <span className="min-w-0">
                      <span className="block font-medium">{e.full_name}</span>
                      <span className="text-xs text-ink-muted">{e.employee_code}{e.date_joined ? ` - joined ${fmtDate(e.date_joined)}` : ''}</span>
                    </span>
                  </span>
                </Td>
                <Td>{e.job_title}{e.company && <span className="block text-xs text-ink-muted">{e.company}</span>}</Td>
                <Td><StatusBadge status={e.status} /></Td>
                <Td>{e.location_ids.map((id) => locationNames.get(id) ?? id).join(', ')}</Td>
                {canManage && (
                  <Td>{e.account?.change_required ? <Badge tone="warn">Temporary password</Badge> : e.account?.last_login_at ? fmtDateTime(e.account.last_login_at) : <span className="text-ink-muted">Never</span>}</Td>
                )}
                {canManage && <Td><div className="flex items-center justify-end gap-2">{rowActions(e)}</div></Td>}
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
      {data?.items.length === 0 && <EmptyState title="No employees found" />}
      {data && <Pagination page={page} size={SIZE} total={data.total} onPage={setPage} />}

      {formOpen && (
        <EmployeeForm open employee={editing} supervisors={(all?.items ?? []).filter((x) => x.role_tier !== 'steward')}
          onClose={() => setFormOpen(false)} onSaved={() => { setFormOpen(false); reload() }} />
      )}
      <Modal
        open={enrolling !== null}
        size="md"
        title={`${enrolling?.face_enrolled ? 'Update' : 'Enroll'} face`}
        description={enrolling ? `${enrolling.full_name}. Only a numeric face template is stored, never a photo.` : undefined}
        onClose={() => setEnrolling(null)}
        footer={enrolling?.face_enrolled ? <Button variant="outline" className="mr-auto border-danger/40 text-danger hover:bg-danger-soft" onClick={removeFace}>Remove the face on file</Button> : undefined}
      >
        {enrolling && <FaceCapture onCapture={enroll} />}
      </Modal>
      <ConfirmDialog open={removing !== null} title="Delete employee" confirmLabel="Delete employee"
        message={`Delete ${removing?.full_name ?? 'this employee'} and their sign-in? This cannot be undone. Anyone with attendance, checklist, stock or other history cannot be deleted; deactivate them instead.`}
        onConfirm={confirmRemove} onCancel={() => setRemoving(null)} />
      {resetting && <ResetPasswordModal employee={resetting} onClose={() => setResetting(null)} onDone={reload} />}
      <ConfirmDialog open={toggling !== null} title={toggling?.status === 'active' ? 'Deactivate employee' : 'Activate employee'}
        message={toggling?.status === 'active'
          ? `${toggling?.full_name} will no longer be able to sign in or check in.`
          : `${toggling?.full_name} will be able to sign in again.`}
        confirmLabel={toggling?.status === 'active' ? 'Deactivate' : 'Activate'}
        onConfirm={confirmToggle} onCancel={() => setToggling(null)} />
    </div>
  )
}
