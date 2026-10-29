import { BookOpen, Eye, EyeOff, Pencil, Plus, Trash2, Users } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { CardGrid, RecordCard, SectionHeader } from '@/components/ui/record-card'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import type { CourseRow } from '@/lib/training'
import { useRun } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { AssignModal } from '@/pages/training/AssignModal'
import { CourseEditor } from '@/pages/training/CourseEditor'

const TEXTAREA = 'w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm placeholder:text-ink-muted focus-visible:outline-2 focus-visible:outline-brand'

function CourseForm({ course, onClose, onSaved }: { course: CourseRow | null; onClose: () => void; onSaved: (id: number, created: boolean) => void }) {
  const run = useRun()
  const [title, setTitle] = useState(course?.title ?? '')
  const [category, setCategory] = useState(course?.category ?? '')
  const [description, setDescription] = useState(course?.description ?? '')
  const [passMark, setPassMark] = useState(String(course?.pass_mark ?? 80))
  const [certificate, setCertificate] = useState(course?.certificate ?? true)

  async function save(event: FormEvent) {
    event.preventDefault()
    const body = { title, category: category || null, description: description || null, pass_mark: Number(passMark), certificate }
    let saved: { id: number } | null = null
    const ok = await run(async () => {
      saved = course ? await api(`/training/courses/${course.id}`, { method: 'PUT', body }) : await api('/training/courses', { body })
    }, course ? 'Course saved' : 'Course created')
    if (ok && saved) onSaved((saved as { id: number }).id, !course)
  }

  return (
    <Modal open size="lg" title={course ? 'Edit course details' : 'New course'} onClose={onClose}
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="course-form" disabled={title.trim().length < 2}>{course ? 'Save course' : 'Create and add lessons'}</Button>
      </>}>
      <form id="course-form" onSubmit={save} className="space-y-5">
        <div className="grid gap-5 sm:grid-cols-[1fr_14rem]">
          <Field label="Course title"><Input required autoFocus maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Category (optional)"><Input maxLength={60} placeholder="For example Food safety" value={category} onChange={(e) => setCategory(e.target.value)} /></Field>
        </div>
        <Field label="What this course covers (optional)">
          <textarea className={TEXTAREA} rows={4} maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className="grid items-end gap-5 sm:grid-cols-2">
          <Field label="Quiz pass mark (%)"><Input type="number" min={1} max={100} required value={passMark} onChange={(e) => setPassMark(e.target.value)} /></Field>
          <label className="flex items-center gap-2.5 pb-2 text-sm"><input type="checkbox" checked={certificate} onChange={(e) => setCertificate(e.target.checked)} /> Give a certificate when the course is completed</label>
        </div>
      </form>
    </Modal>
  )
}

/** Every training course: build it, publish it, assign it to people. */
export function SettingsTrainingCourses() {
  const run = useRun()
  const list = useApi<{ items: CourseRow[] }>('/training/courses')
  const [form, setForm] = useState<{ course: CourseRow | null } | null>(null)
  const [editing, setEditing] = useState<number | null>(null)
  const [assigning, setAssigning] = useState<CourseRow | null>(null)
  const [removing, setRemoving] = useState<CourseRow | null>(null)

  async function setStatus(course: CourseRow, status: 'draft' | 'published') {
    if (await run(() => api(`/training/courses/${course.id}`, { method: 'PUT', body: { status } }), status === 'published' ? 'Course published' : 'Course unpublished')) list.reload()
  }

  async function remove() {
    if (!removing) return
    if (await run(() => api(`/training/courses/${removing.id}`, { method: 'DELETE' }), 'Course deleted')) {
      setRemoving(null)
      list.reload()
    }
  }

  const items = list.data?.items ?? []
  return (
    <div className="space-y-6">
      <SectionHeader title="Training courses" count={list.data ? items.length : undefined}
        action={<Button onClick={() => setForm({ course: null })}><Plus className="h-4 w-4" /> New course</Button>} />

      {!list.data ? <Skeleton className="h-48 w-full" /> : items.length === 0 ? (
        <EmptyState title="No courses yet" action={<Button onClick={() => setForm({ course: null })}><Plus className="h-4 w-4" /> Create the first course</Button>} />
      ) : (
        <CardGrid>
          {items.map((course) => (
            <RecordCard key={course.id} title={course.title} subtitle={course.category ?? undefined}
              badges={<Badge tone={course.status === 'published' ? 'ok' : 'neutral'}>{course.status === 'published' ? 'Published' : 'Draft'}</Badge>}
              facts={[
                { label: 'Lessons', value: course.lessons },
                { label: 'Assigned', value: course.assigned },
                { label: 'Completed', value: `${course.completed} of ${course.assigned}` },
                { label: 'Pass mark', value: `${course.pass_mark}%` },
              ]}
              actions={[
                { label: 'Lessons and files', icon: BookOpen, onClick: () => setEditing(course.id) },
                { label: 'Assign', icon: Users, onClick: () => setAssigning(course), disabled: course.status !== 'published', title: course.status !== 'published' ? 'Publish the course first' : undefined },
                course.status === 'published'
                  ? { label: 'Unpublish', icon: EyeOff, onClick: () => setStatus(course, 'draft') }
                  : { label: 'Publish', icon: Eye, onClick: () => setStatus(course, 'published') },
                { label: 'Edit details', icon: Pencil, onClick: () => setForm({ course }) },
                { label: 'Delete', icon: Trash2, tone: 'danger', onClick: () => setRemoving(course) },
              ]} />
          ))}
        </CardGrid>
      )}

      {form && <CourseForm course={form.course} onClose={() => setForm(null)}
        onSaved={(id, created) => { setForm(null); list.reload(); if (created) setEditing(id) }} />}
      {editing !== null && <CourseEditor courseId={editing} onClose={() => setEditing(null)} onChanged={list.reload} />}
      {assigning && <AssignModal course={assigning} onClose={() => setAssigning(null)} onDone={() => { setAssigning(null); list.reload() }} />}
      <ConfirmDialog open={removing !== null} title="Delete course" confirmLabel="Delete course"
        message={`Delete "${removing?.title ?? 'this course'}" with its lessons and files? A course people have been assigned cannot be deleted; unpublish it instead.`}
        onConfirm={remove} onCancel={() => setRemoving(null)} />
    </div>
  )
}
