import { ArrowDown, ArrowUp, Eye, EyeOff, ListChecks, Pencil, Play, Plus, Presentation, Trash2, Upload, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { ProgressBar } from '@/components/ProgressBar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { FILE_ACCEPT, KIND_ICON, KIND_LABEL, VIDEO_STATUS_LABEL, fileSize, isMaking, takesFile, type AdminCourse, type AdminLesson, type LessonKind } from '@/lib/training'
import { useRun } from '@/lib/toast'
import { uploadWithProgress } from '@/lib/uploadProgress'
import { useApi } from '@/lib/useApi'
import { MediaPreview } from '@/pages/training/MediaPreview'
import { QuizEditor } from '@/pages/training/QuizEditor'
import { SlideVideoEditor } from '@/pages/training/SlideVideoEditor'

const TEXTAREA = 'w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm placeholder:text-ink-muted focus-visible:outline-2 focus-visible:outline-brand'
const KINDS = Object.keys(KIND_LABEL) as LessonKind[]

function LessonForm({ courseId, lesson, onClose, onSaved }: { courseId: number; lesson: AdminLesson | null; onClose: () => void; onSaved: () => void }) {
  const run = useRun()
  const [title, setTitle] = useState(lesson?.title ?? '')
  const [kind, setKind] = useState<LessonKind>(lesson?.kind ?? 'video')
  const [body, setBody] = useState(lesson?.body ?? '')
  const [url, setUrl] = useState(lesson?.external_url ?? '')

  async function save(event: FormEvent) {
    event.preventDefault()
    const data = { title, kind, body: body.trim() || null, external_url: kind === 'link' ? url.trim() || null : null }
    const ok = await run(() => (lesson ? api(`/training/lessons/${lesson.id}`, { method: 'PUT', body: data }) : api(`/training/courses/${courseId}/lessons`, { body: data })),
      lesson ? 'Lesson saved' : 'Lesson added')
    if (ok) onSaved()
  }

  return (
    <Modal open size="lg" title={lesson ? 'Edit lesson' : 'Add a lesson'} onClose={onClose}
      description={takesFile(kind) ? 'Save the lesson, then upload its file from the lessons list.' : undefined}
      footer={<>
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="lesson-form" disabled={title.trim().length < 2}>{lesson ? 'Save lesson' : 'Add lesson'}</Button>
      </>}>
      <form id="lesson-form" onSubmit={save} className="space-y-5">
        <div className="grid gap-5 sm:grid-cols-[1fr_12rem]">
          <Field label="Lesson title"><Input required autoFocus maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Kind">
            <Select value={kind} onChange={(e) => setKind(e.target.value as LessonKind)}>
              {KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </Select>
          </Field>
        </div>
        {kind === 'link' && <Field label="Link"><Input type="url" required placeholder="https://" maxLength={500} value={url} onChange={(e) => setUrl(e.target.value)} /></Field>}
        <Field label={kind === 'text' ? 'Lesson text' : 'Notes shown with the lesson (optional)'}>
          <textarea className={TEXTAREA} rows={kind === 'text' ? 10 : 4} maxLength={20000} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        {kind === 'quiz' && <p className="text-sm text-ink-muted">Save the lesson, then use "Questions" in the lessons list to write the quiz.</p>}
      </form>
    </Modal>
  )
}

interface RowProps {
  lesson: AdminLesson
  index: number
  count: number
  progress: number | undefined
  onMove: (direction: -1 | 1) => void
  onEdit: () => void
  onDelete: () => void
  onUpload: (file: File) => void
  onRemoveFile: () => void
  onQuiz: () => void
  onSlides: () => void
  onWatch: () => void
}

function LessonRow({ lesson, index, count, progress, onMove, onEdit, onDelete, onUpload, onRemoveFile, onQuiz, onSlides, onWatch }: RowProps) {
  const picker = useRef<HTMLInputElement>(null)
  const Icon = KIND_ICON[lesson.kind]
  const kind = lesson.kind
  const fromSlides = kind === 'video' && lesson.slides.length > 0
  const making = isMaking(lesson.video)
  const detail = fromSlides
    ? `${lesson.slides.length} ${lesson.slides.length === 1 ? 'slide' : 'slides'}${lesson.video.status ? `, ${VIDEO_STATUS_LABEL[lesson.video.status].toLowerCase()}` : ''}${lesson.media ? `, ${fileSize(lesson.media.size)}` : ''}`
    : takesFile(kind)
    ? (lesson.media ? `${lesson.media.original}  ${fileSize(lesson.media.size)}` : 'No file yet')
    : kind === 'link' ? (lesson.external_url || 'No link yet')
    : kind === 'quiz' ? `${lesson.questions.length} ${lesson.questions.length === 1 ? 'question' : 'questions'}`
    : (lesson.body?.trim() ? lesson.body.trim().slice(0, 80) : 'No text yet')
  const missing = making || (takesFile(kind) && !lesson.media) || (kind === 'link' && !lesson.external_url) || (kind === 'quiz' && lesson.questions.length === 0) || (kind === 'text' && !lesson.body?.trim())

  return (
    <li className="space-y-3 rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-deep"><Icon aria-hidden className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1">
          <p className="font-medium">{index + 1}. {lesson.title} <Badge className="ml-1">{KIND_LABEL[kind]}</Badge></p>
          <p className={`truncate text-sm ${missing ? 'text-warn' : 'text-ink-muted'}`}>{detail}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button type="button" variant="ghost" size="icon" aria-label={`Move ${lesson.title} up`} disabled={index === 0} onClick={() => onMove(-1)}><ArrowUp className="h-4 w-4" /></Button>
          <Button type="button" variant="ghost" size="icon" aria-label={`Move ${lesson.title} down`} disabled={index === count - 1} onClick={() => onMove(1)}><ArrowDown className="h-4 w-4" /></Button>
        </div>
      </div>
      {progress !== undefined && (
        <div className="space-y-1">
          <ProgressBar percent={progress} label={`Uploading ${lesson.title}`} />
          <p className="text-xs text-ink-muted">Uploading {progress}%. Keep this window open until it finishes.</p>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {takesFile(kind) && (
          <>
            <input ref={picker} type="file" hidden accept={FILE_ACCEPT[kind]} aria-label={`File for ${lesson.title}`}
              onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) onUpload(file) }} />
            <Button type="button" size="sm" variant="outline" disabled={progress !== undefined || making} onClick={() => picker.current?.click()}>
              <Upload className="h-3.5 w-3.5" /> {lesson.media ? 'Replace file' : 'Upload file'}
            </Button>
            {kind === 'video' && <Button type="button" size="sm" variant="outline" onClick={onSlides}><Presentation className="h-3.5 w-3.5" /> {lesson.slides.length ? 'Edit slides' : 'Make from slides'}</Button>}
            {lesson.media && (kind === 'video' || kind === 'audio') && <Button type="button" size="sm" variant="outline" onClick={onWatch}><Play className="h-3.5 w-3.5" /> {kind === 'video' ? 'Watch' : 'Listen'}</Button>}
            {lesson.media && <Button type="button" size="sm" variant="outline" disabled={progress !== undefined || making} onClick={onRemoveFile}><X className="h-3.5 w-3.5" /> Remove file</Button>}
          </>
        )}
        {kind === 'quiz' && <Button type="button" size="sm" variant="outline" onClick={onQuiz}><ListChecks className="h-3.5 w-3.5" /> Questions</Button>}
        <Button type="button" size="sm" variant="outline" onClick={onEdit}><Pencil className="h-3.5 w-3.5" /> Edit</Button>
        <Button type="button" size="sm" variant="outline" className="border-danger/40 text-danger hover:bg-danger-soft" onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /> Delete</Button>
      </div>
    </li>
  )
}

/** Where a manager builds a course: add lessons, give each its file or text, order them, and publish. */
export function CourseEditor({ courseId, onClose, onChanged }: { courseId: number; onClose: () => void; onChanged: () => void }) {
  const run = useRun()
  const course = useApi<AdminCourse>(`/training/courses/${courseId}`)
  const [form, setForm] = useState<{ lesson: AdminLesson | null } | null>(null)
  const [quizFor, setQuizFor] = useState<AdminLesson | null>(null)
  const [removing, setRemoving] = useState<AdminLesson | null>(null)
  const [slidesFor, setSlidesFor] = useState<number | null>(null)
  const [watching, setWatching] = useState<AdminLesson | null>(null)
  const [uploading, setUploading] = useState<Record<number, number>>({})
  const data = course.data
  const lessons = data?.lesson_list ?? []

  const refresh = () => { course.reload(); onChanged() }

  // a video being made from slides finishes in the background; keep the list up to date until it does
  const anyMaking = lessons.some((l) => isMaking(l.video))
  const reload = course.reload
  useEffect(() => {
    if (!anyMaking) return
    const timer = setInterval(reload, 3000)
    return () => clearInterval(timer)
  }, [anyMaking, reload])

  async function move(index: number, direction: -1 | 1) {
    const order = lessons.map((l) => l.id)
    ;[order[index], order[index + direction]] = [order[index + direction], order[index]]
    if (await run(() => api(`/training/courses/${courseId}/lessons/reorder`, { body: { lesson_ids: order } }))) refresh()
  }

  async function upload(lesson: AdminLesson, file: File) {
    setUploading((all) => ({ ...all, [lesson.id]: 0 }))
    const ok = await run(() => uploadWithProgress(`/training/lessons/${lesson.id}/media`, file, (percent) => setUploading((all) => ({ ...all, [lesson.id]: percent }))), 'File uploaded')
    setUploading((all) => { const rest = { ...all }; delete rest[lesson.id]; return rest })
    if (ok) refresh()
  }

  async function removeFile(lesson: AdminLesson) {
    if (await run(() => api(`/training/lessons/${lesson.id}/media`, { method: 'DELETE' }), 'File removed')) refresh()
  }

  async function deleteLesson() {
    if (!removing) return
    if (await run(() => api(`/training/lessons/${removing.id}`, { method: 'DELETE' }), 'Lesson deleted')) {
      setRemoving(null)
      refresh()
    }
  }

  async function setStatus(status: 'draft' | 'published') {
    if (await run(() => api(`/training/courses/${courseId}`, { method: 'PUT', body: { status } }), status === 'published' ? 'Course published' : 'Course unpublished')) refresh()
  }

  const nested = form !== null || quizFor !== null || removing !== null || slidesFor !== null || watching !== null
  return (
    <>
      <Modal open={!nested} size="xl" title={data ? data.title : 'Course'} onClose={onClose}
        description="Add lessons, give each its file or text, put them in order, then publish the course so it can be assigned."
        footer={<>
          <Button type="button" variant="outline" onClick={onClose}>Close</Button>
          {data && (data.status === 'published'
            ? <Button type="button" variant="outline" onClick={() => setStatus('draft')}><EyeOff className="h-4 w-4" /> Unpublish</Button>
            : <Button type="button" disabled={data.problems.length > 0} onClick={() => setStatus('published')}><Eye className="h-4 w-4" /> Publish course</Button>)}
        </>}>
        {!data ? <Skeleton className="h-48 w-full" /> : (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={data.status === 'published' ? 'ok' : 'neutral'}>{data.status === 'published' ? 'Published' : 'Draft'}</Badge>
              {data.category && <Badge>{data.category}</Badge>}
              <span className="text-sm text-ink-muted">{lessons.length} {lessons.length === 1 ? 'lesson' : 'lessons'}, pass mark {data.pass_mark}%{data.certificate ? ', certificate on completion' : ''}</span>
            </div>
            {data.status !== 'published' && data.problems.length > 0 && (
              <div role="status" className="rounded-xl bg-warn-soft p-4 text-sm text-warn">
                <p className="font-medium">Before this course can be published:</p>
                <ul className="mt-1 list-disc pl-5">{data.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
              </div>
            )}
            {lessons.length === 0 ? <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-ink-muted">No lessons yet. Add the first one.</p> : (
              <ol className="space-y-3">
                {lessons.map((lesson, index) => (
                  <LessonRow key={lesson.id} lesson={lesson} index={index} count={lessons.length} progress={uploading[lesson.id]}
                    onMove={(direction) => move(index, direction)} onEdit={() => setForm({ lesson })} onDelete={() => setRemoving(lesson)}
                    onUpload={(file) => upload(lesson, file)} onRemoveFile={() => removeFile(lesson)} onQuiz={() => setQuizFor(lesson)}
                    onSlides={() => setSlidesFor(lesson.id)} onWatch={() => setWatching(lesson)} />
                ))}
              </ol>
            )}
            <Button type="button" onClick={() => setForm({ lesson: null })}><Plus className="h-4 w-4" /> Add a lesson</Button>
          </div>
        )}
      </Modal>

      {form && <LessonForm courseId={courseId} lesson={form.lesson} onClose={() => setForm(null)} onSaved={() => { setForm(null); refresh() }} />}
      {quizFor && <QuizEditor lesson={quizFor} onClose={() => setQuizFor(null)} onSaved={() => { setQuizFor(null); refresh() }} />}
      {slidesFor !== null && <SlideVideoEditor courseId={courseId} lessonId={slidesFor} onClose={() => { setSlidesFor(null); refresh() }} onChanged={refresh} />}
      {watching && <MediaPreview lessonId={watching.id} title={watching.title} onClose={() => setWatching(null)} />}
      <ConfirmDialog open={removing !== null} title="Delete lesson" confirmLabel="Delete lesson"
        message={`Delete "${removing?.title ?? 'this lesson'}"? Its file and any progress people made on it are removed. This cannot be undone.`}
        onConfirm={deleteLesson} onCancel={() => setRemoving(null)} />
    </>
  )
}
