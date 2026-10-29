import { Award, Download, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { ProgressBar } from '@/components/ProgressBar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SectionHeader } from '@/components/ui/record-card'
import { Select } from '@/components/ui/select'
import { EmptyState, SkeletonRows, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { downloadFile } from '@/lib/download'
import { fmtDate, fmtDateTime } from '@/lib/format'
import { STATUS_LABEL, type CourseRow, type ProgressRow } from '@/lib/training'
import { useRun, useToast } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'

interface Summary { assigned: number; completed: number; in_progress: number; not_started: number; overdue: number }

/** Who has which course, how far they have got, and who is behind; with the certificates and a spreadsheet of it all. */
export function SettingsTrainingProgress() {
  const run = useRun()
  const toast = useToast()
  const courses = useApi<{ items: CourseRow[] }>('/training/courses')
  const [courseId, setCourseId] = useState('')
  const [search, setSearch] = useState('')
  const [removing, setRemoving] = useState<ProgressRow | null>(null)
  const progress = useApi<{ items: ProgressRow[]; summary: Summary }>(`/training/progress${qs({ course_id: courseId })}`)

  const needle = search.trim().toLowerCase()
  const rows = (progress.data?.items ?? []).filter((r) => !needle || `${r.employee} ${r.employee_code} ${r.course} ${r.locations.join(' ')}`.toLowerCase().includes(needle))
  const summary = progress.data?.summary

  async function exportCsv() {
    if (!(await downloadFile(`/api/training/progress.csv${qs({ course_id: courseId })}`, 'training-progress.csv'))) toast('error', 'The export could not be downloaded')
  }

  async function certificate(row: ProgressRow) {
    if (!(await downloadFile(`/api/training/assignments/${row.assignment_id}/certificate`, `${row.certificate_no}.pdf`))) toast('error', 'The certificate could not be downloaded')
  }

  async function takeBack() {
    if (!removing) return
    if (await run(() => api(`/training/assignments/${removing.assignment_id}`, { method: 'DELETE' }), 'Training taken back')) {
      setRemoving(null)
      progress.reload()
      courses.reload()
    }
  }

  return (
    <div className="space-y-6">
      <SectionHeader title="Training progress" count={progress.data ? rows.length : undefined}
        action={<Button variant="outline" onClick={exportCsv}><Download className="h-4 w-4" /> Export to Excel (CSV)</Button>} />

      <div className="filter-bar">
        <Select aria-label="Course" className="w-auto" value={courseId} onChange={(e) => setCourseId(e.target.value)}>
          <option value="">All courses</option>
          {courses.data?.items.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
        </Select>
        <Input aria-label="Search people or courses" type="search" className="w-64" placeholder="Search name, code or location" value={search} onChange={(e) => setSearch(e.target.value)} />
        {summary && (
          <div className="ml-auto flex flex-wrap gap-2">
            <Badge>{summary.assigned} assigned</Badge>
            <Badge tone="ok">{summary.completed} completed</Badge>
            <Badge tone="warn">{summary.in_progress} in progress</Badge>
            <Badge>{summary.not_started} not started</Badge>
            {summary.overdue > 0 && <Badge tone="critical">{summary.overdue} overdue</Badge>}
          </div>
        )}
      </div>

      <Table>
        <thead><tr><Th>Person</Th><Th>Course</Th><Th>Locations</Th><Th>Status</Th><Th className="w-44">Progress</Th><Th>Due</Th><Th>Last activity</Th><Th>Completed</Th><Th /></tr></thead>
        <tbody>
          {!progress.data ? <SkeletonRows cols={9} /> : rows.map((r) => (
            <tr key={r.assignment_id}>
              <Td><span className="block font-medium">{r.employee}</span><span className="block text-xs text-ink-muted">{r.job_title}</span></Td>
              <Td>{r.course}</Td>
              <Td className="text-ink-muted">{r.locations.join(', ') || '-'}</Td>
              <Td><Badge tone={r.status === 'completed' ? 'ok' : r.overdue ? 'critical' : r.status === 'in_progress' ? 'warn' : 'neutral'}>{r.overdue ? 'Overdue' : STATUS_LABEL[r.status]}</Badge></Td>
              <Td>
                <ProgressBar percent={r.percent} label={`${r.employee}, ${r.course}`} tone={r.status === 'completed' ? 'ok' : 'brand'} />
                <span className="mt-1 block text-xs text-ink-muted">{r.done} of {r.lessons} lessons ({r.percent}%)</span>
              </Td>
              <Td>{r.due_on ? fmtDate(r.due_on) : '-'}</Td>
              <Td className="text-ink-muted">{r.last_activity ? fmtDateTime(r.last_activity) : '-'}</Td>
              <Td>{r.completed_at ? <>{fmtDate(r.completed_at.slice(0, 10))}{r.score != null && <span className="block text-xs text-ink-muted">quiz {r.score}%</span>}</> : '-'}</Td>
              <Td>
                <div className="flex gap-2">
                  {r.certificate_no && <Button size="sm" variant="outline" aria-label={`Certificate for ${r.employee}`} onClick={() => certificate(r)}><Award className="h-3.5 w-3.5" /></Button>}
                  {r.status !== 'completed' && <Button size="sm" variant="outline" className="border-danger/40 text-danger hover:bg-danger-soft" aria-label={`Take back ${r.course} from ${r.employee}`} onClick={() => setRemoving(r)}><Trash2 className="h-3.5 w-3.5" /></Button>}
                </div>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {progress.data && rows.length === 0 && <EmptyState title="Nothing has been assigned yet" />}

      <ConfirmDialog open={removing !== null} title="Take back this training" confirmLabel="Take it back"
        message={`Take "${removing?.course ?? ''}" back from ${removing?.employee ?? 'this person'}? Their progress on it is removed. Finished training stays on record and cannot be taken back.`}
        onConfirm={takeBack} onCancel={() => setRemoving(null)} />
    </div>
  )
}
