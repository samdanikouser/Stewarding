import { Award, CalendarClock, GraduationCap, Play, RotateCcw, Settings } from 'lucide-react'
import { Link } from 'react-router-dom'
import { KpiCard } from '@/components/KpiCard'
import { ProgressBar } from '@/components/ProgressBar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { EmptyState, Skeleton } from '@/components/ui/table'
import { useAuth } from '@/lib/auth'
import { downloadFile } from '@/lib/download'
import { fmtDate } from '@/lib/format'
import { STATUS_LABEL, type CourseSummary } from '@/lib/training'
import { useToast } from '@/lib/toast'
import { useApi } from '@/lib/useApi'

function CourseCard({ course }: { course: CourseSummary }) {
  const toast = useToast()
  const finished = course.status === 'completed'

  async function certificate() {
    if (!(await downloadFile(`/api/training/my/${course.assignment_id}/certificate`, 'certificate.pdf'))) toast('error', 'The certificate could not be downloaded')
  }

  return (
    <Card className="flex flex-col transition-shadow hover:shadow-md">
      <div className="flex-1 space-y-4 p-5">
        <div className="flex items-start gap-3">
          <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${finished ? 'bg-ok-soft text-ok' : 'bg-brand-soft text-brand-deep'}`}>
            {finished ? <Award aria-hidden className="h-5 w-5" /> : <GraduationCap aria-hidden className="h-5 w-5" />}
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold leading-snug">{course.title}</h3>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              <Badge tone={finished ? 'ok' : course.overdue ? 'critical' : course.status === 'in_progress' ? 'warn' : 'neutral'}>
                {course.overdue ? 'Overdue' : STATUS_LABEL[course.status]}
              </Badge>
              {course.category && <Badge>{course.category}</Badge>}
            </div>
          </div>
        </div>
        {course.description && <p className="line-clamp-2 text-sm text-ink-muted">{course.description}</p>}
        <div className="space-y-1.5">
          <ProgressBar percent={course.percent} label={`${course.title} progress`} tone={finished ? 'ok' : 'brand'} />
          <div className="flex items-center justify-between text-xs text-ink-muted">
            <span>{course.done} of {course.lessons} lessons</span>
            <span>{course.percent}%</span>
          </div>
        </div>
        {course.due_on && !finished && (
          <p className={`flex items-center gap-1.5 text-xs ${course.overdue ? 'font-medium text-danger' : 'text-ink-muted'}`}>
            <CalendarClock aria-hidden className="h-3.5 w-3.5" /> {course.overdue ? 'Was due' : 'Due'} {fmtDate(course.due_on)}
          </p>
        )}
        {finished && course.completed_at && <p className="text-xs text-ink-muted">Completed {fmtDate(course.completed_at.slice(0, 10))}{course.score != null && `, quiz result ${course.score}%`}</p>}
      </div>
      <div className="flex flex-wrap gap-2 border-t border-border p-4">
        <Button asChild variant={finished ? 'outline' : 'default'} className="flex-1">
          <Link to={`/training/${course.assignment_id}`}>
            {finished ? <RotateCcw className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {finished ? 'Review' : course.status === 'in_progress' ? 'Continue' : 'Start'}
          </Link>
        </Button>
        {finished && course.certificate && <Button variant="outline" onClick={certificate}><Award className="h-4 w-4" /> Certificate</Button>}
      </div>
    </Card>
  )
}

/** The training assigned to the signed-in person, what is left to do first, and a certificate for what is finished. */
export function TrainingPage() {
  const { me } = useAuth()
  const { data, loading } = useApi<{ items: CourseSummary[] }>('/training/my')
  const items = data?.items ?? []
  const open = items.filter((c) => c.status !== 'completed')
  const done = items.filter((c) => c.status === 'completed')

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Training</h1>
          <p className="mt-1 text-sm text-ink-muted">Your courses, with your progress kept as you go.</p>
        </div>
        {me?.permissions.includes('settings.manage') && (
          <Button asChild variant="outline"><Link to="/settings/training-courses"><Settings className="h-4 w-4" /> Manage training</Link></Button>
        )}
      </div>

      {loading && !data ? <Skeleton className="h-48 w-full" /> : items.length === 0 ? (
        <EmptyState title="No training has been assigned to you yet" />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <KpiCard label="To do" value={open.filter((c) => c.status === 'not_started').length} icon={GraduationCap} />
            <KpiCard label="In progress" value={open.filter((c) => c.status === 'in_progress').length} icon={Play} />
            <KpiCard label="Completed" value={done.length} icon={Award} />
          </div>

          {open.length > 0 && (
            <section aria-labelledby="training-open" className="space-y-3">
              <h2 id="training-open" className="text-lg font-semibold">To do</h2>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{open.map((c) => <CourseCard key={c.assignment_id} course={c} />)}</div>
            </section>
          )}
          {done.length > 0 && (
            <section aria-labelledby="training-done" className="space-y-3">
              <h2 id="training-done" className="text-lg font-semibold">Completed</h2>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{done.map((c) => <CourseCard key={c.assignment_id} course={c} />)}</div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
