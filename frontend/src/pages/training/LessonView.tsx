import { ArrowRight, Check, CheckCircle2, Download, ExternalLink } from 'lucide-react'
import { useRef, type SyntheticEvent } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { KIND_ICON, KIND_LABEL, fileSize, type PlayerLesson } from '@/lib/training'
import { useRun, useToast } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { QuizPanel } from '@/pages/training/QuizPanel'

interface MediaLink {
  url: string
  original: string
  type: string
  inline: boolean
}

interface Props {
  assignmentId: number
  lesson: PlayerLesson
  hasNext: boolean
  onNext: () => void
  onChanged: () => void
}

/** One lesson: its video, audio, document, text, link or quiz, with a way to mark it done and move on. */
export function LessonView({ assignmentId, lesson, hasNext, onNext, onChanged }: Props) {
  const run = useRun()
  const toast = useToast()
  const base = `/training/my/${assignmentId}/lessons/${lesson.id}`
  const link = useApi<MediaLink>(lesson.media ? `${base}/media-url` : null)
  const lastSaved = useRef(0)
  const Icon = KIND_ICON[lesson.kind]

  // where a video or audio was left is kept every ten seconds and on pause, so it picks up from there next time
  function savePosition(seconds: number) {
    lastSaved.current = seconds
    api(`${base}/position`, { body: { position_seconds: Math.floor(seconds) } }).catch(() => undefined)
  }

  async function markDone(quietly = false) {
    let finishedCourse = false
    const ok = await run(async () => {
      finishedCourse = (await api<{ course_completed: boolean }>(`${base}/complete`, { method: 'POST' })).course_completed
    }, quietly ? undefined : 'Lesson marked as complete')
    if (ok) {
      if (finishedCourse) toast('ok', 'Course complete. Well done!')
      onChanged()
    }
  }

  const player = {
    controls: true,
    preload: 'metadata' as const,
    controlsList: 'nodownload',
    src: link.data?.url,
    onLoadedMetadata: (event: SyntheticEvent<HTMLMediaElement>) => {
      const element = event.currentTarget
      // pick up where it was left, unless that was a glance at the start or it was practically finished
      if (lesson.position_seconds > 5 && lesson.position_seconds < element.duration * 0.97) element.currentTime = lesson.position_seconds
    },
    onTimeUpdate: (event: SyntheticEvent<HTMLMediaElement>) => {
      const seconds = event.currentTarget.currentTime
      if (Math.abs(seconds - lastSaved.current) >= 10) savePosition(seconds)
    },
    onPause: (event: SyntheticEvent<HTMLMediaElement>) => savePosition(event.currentTarget.currentTime),
    onEnded: () => { if (!lesson.completed) void markDone(true) },
  }

  const waiting = lesson.media && !link.data
  const content = lesson.kind === 'quiz' ? (
    <QuizPanel assignmentId={assignmentId} lesson={lesson} onChanged={onChanged} />
  ) : lesson.kind === 'text' ? (
    <div className="whitespace-pre-wrap text-base leading-7">{lesson.body}</div>
  ) : lesson.kind === 'link' ? (
    <div className="space-y-3 rounded-xl border border-border bg-surface p-5">
      <p className="break-all text-sm text-ink-muted">{lesson.external_url}</p>
      <Button asChild><a href={lesson.external_url ?? '#'} target="_blank" rel="noopener noreferrer"><ExternalLink className="h-4 w-4" /> Open the link</a></Button>
    </div>
  ) : waiting ? (
    <div className="aspect-video w-full animate-pulse rounded-xl bg-surface-muted" aria-label="Loading" />
  ) : lesson.kind === 'video' && link.data ? (
    <video {...player} playsInline className="aspect-video w-full rounded-xl bg-black">Your browser cannot play this video.</video>
  ) : lesson.kind === 'audio' && link.data ? (
    <div className="space-y-3 rounded-xl border border-border bg-surface p-5">
      <p className="text-sm font-medium">{link.data.original}</p>
      <audio {...player} className="w-full">Your browser cannot play this audio.</audio>
    </div>
  ) : lesson.kind === 'document' && link.data ? (
    <div className="space-y-4 rounded-xl border border-border bg-surface p-5">
      {link.data.type.startsWith('image/') && <img src={link.data.url} alt={link.data.original} className="max-h-[32rem] w-full rounded-lg object-contain" />}
      <p className="text-sm"><span className="font-medium">{link.data.original}</span> <span className="text-ink-muted">{fileSize(lesson.media?.size)}</span></p>
      <div className="flex flex-wrap gap-2">
        {link.data.inline && !link.data.type.startsWith('image/') && (
          <Button asChild><a href={link.data.url} target="_blank" rel="noopener noreferrer"><ExternalLink className="h-4 w-4" /> Open</a></Button>
        )}
        <Button asChild variant="outline"><a href={link.data.url} download={link.data.original}><Download className="h-4 w-4" /> Download</a></Button>
      </div>
    </div>
  ) : (
    <p className="text-sm text-ink-muted">This lesson has no content yet.</p>
  )

  return (
    <article className="space-y-5">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge><Icon aria-hidden className="mr-1 inline h-3.5 w-3.5" />{KIND_LABEL[lesson.kind]}</Badge>
          {lesson.completed && <Badge tone="ok">Completed</Badge>}
        </div>
        <h2 className="text-xl font-semibold tracking-tight">{lesson.title}</h2>
      </div>

      {content}

      {lesson.kind !== 'text' && lesson.body && <p className="whitespace-pre-wrap text-sm text-ink-muted">{lesson.body}</p>}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        {lesson.kind !== 'quiz' && !lesson.completed && <Button onClick={() => markDone()}><Check className="h-4 w-4" /> Mark as complete</Button>}
        {lesson.completed && <span className="flex items-center gap-1.5 text-sm font-medium text-ok"><CheckCircle2 aria-hidden className="h-4 w-4" /> Done</span>}
        {hasNext && <Button variant={lesson.completed ? 'default' : 'outline'} onClick={onNext}>Next lesson <ArrowRight className="h-4 w-4" /></Button>}
      </div>
    </article>
  )
}
