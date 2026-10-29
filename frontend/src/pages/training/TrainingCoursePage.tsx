import { Award, CalendarClock, CheckCircle2, ChevronLeft, Circle } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ProgressBar } from '@/components/ProgressBar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/table'
import { downloadFile } from '@/lib/download'
import { fmtDate } from '@/lib/format'
import { KIND_ICON, STATUS_LABEL, type CourseDetail } from '@/lib/training'
import { useToast } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { LessonView } from '@/pages/training/LessonView'

/** One course for the person taking it: the lessons down the side, the open lesson in the middle, and progress kept as they go. */
export function TrainingCoursePage() {
  const { assignmentId } = useParams()
  const id = Number(assignmentId)
  const course = useApi<CourseDetail>(`/training/my/${id}`)
  const toast = useToast()
  const [picked, setPicked] = useState<number | null>(null)
  const data = course.data

  if (course.error && !data) {
    return (
      <div className="space-y-3">
        <Link to="/training" className="inline-flex items-center gap-1 text-sm font-medium text-brand-deep hover:underline"><ChevronLeft className="h-4 w-4" /> All training</Link>
        <p role="alert" className="rounded-xl bg-danger-soft p-4 text-sm text-danger">{course.error}</p>
      </div>
    )
  }
  if (!data) return <Skeleton className="h-96 w-full" />

  const lessons = data.lesson_list
  const current = lessons.find((l) => l.id === picked) ?? lessons.find((l) => !l.completed) ?? lessons[0]
  const index = lessons.indexOf(current)
  const next = lessons[index + 1]

  async function certificate() {
    if (!(await downloadFile(`/api/training/my/${id}/certificate`, 'certificate.pdf'))) toast('error', 'The certificate could not be downloaded')
  }

  return (
    <div className="space-y-5">
      <Link to="/training" className="inline-flex items-center gap-1 text-sm font-medium text-brand-deep hover:underline"><ChevronLeft className="h-4 w-4" /> All training</Link>

      <Card>
        <CardContent className="space-y-4 p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <h1 className="text-2xl font-semibold tracking-tight">{data.title}</h1>
              {data.description && <p className="max-w-3xl text-sm text-ink-muted">{data.description}</p>}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={data.status === 'completed' ? 'ok' : data.overdue ? 'critical' : data.status === 'in_progress' ? 'warn' : 'neutral'}>
                {data.overdue ? 'Overdue' : STATUS_LABEL[data.status]}
              </Badge>
              {data.due_on && data.status !== 'completed' && <span className="flex items-center gap-1 text-xs text-ink-muted"><CalendarClock aria-hidden className="h-3.5 w-3.5" /> Due {fmtDate(data.due_on)}</span>}
            </div>
          </div>
          <div className="space-y-1.5">
            <ProgressBar percent={data.percent} label={`${data.title} progress`} tone={data.status === 'completed' ? 'ok' : 'brand'} />
            <p className="text-xs text-ink-muted">{data.done} of {data.lessons} lessons done ({data.percent}%)</p>
          </div>
          {data.status === 'completed' && (
            <div className="flex flex-wrap items-center gap-3 rounded-xl bg-ok-soft p-4 text-ok">
              <Award aria-hidden className="h-6 w-6 shrink-0" />
              <p className="flex-1 text-sm font-medium">You completed this course{data.completed_at && ` on ${fmtDate(data.completed_at.slice(0, 10))}`}{data.score != null && ` with a quiz result of ${data.score}%`}.</p>
              {data.certificate && <Button onClick={certificate}>Download certificate</Button>}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[18rem_1fr]">
        <nav aria-label="Lessons" className="lg:sticky lg:top-4 lg:self-start">
          <ol className="space-y-1.5">
            {lessons.map((lesson, position) => {
              const Icon = KIND_ICON[lesson.kind]
              const active = lesson.id === current.id
              return (
                <li key={lesson.id}>
                  <button type="button" aria-current={active ? 'true' : undefined} onClick={() => setPicked(lesson.id)}
                    className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-sm transition ${active ? 'border-brand bg-brand-soft font-medium' : 'border-border bg-surface hover:bg-surface-muted'}`}>
                    {lesson.completed ? <CheckCircle2 aria-label="Done" className="h-5 w-5 shrink-0 text-ok" /> : <Circle aria-label="Not done" className="h-5 w-5 shrink-0 text-ink-muted" />}
                    <span className="min-w-0 flex-1"><span className="block truncate">{position + 1}. {lesson.title}</span></span>
                    <Icon aria-hidden className="h-4 w-4 shrink-0 text-ink-muted" />
                  </button>
                </li>
              )
            })}
          </ol>
        </nav>

        <Card>
          <CardContent className="p-6">
            {current ? (
              <LessonView key={current.id} assignmentId={id} lesson={current} hasNext={Boolean(next)} onNext={() => setPicked(next.id)}
                onChanged={() => { setPicked(current.id); course.reload() }} />
            ) : (
              <p className="text-sm text-ink-muted">This course has no lessons yet.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
