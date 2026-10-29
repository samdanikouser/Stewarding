import { AlignLeft, FileText, Headphones, Link2, ListChecks, Video, type LucideIcon } from 'lucide-react'

export type LessonKind = 'video' | 'audio' | 'document' | 'text' | 'link' | 'quiz'

export const KIND_LABEL: Record<LessonKind, string> = { video: 'Video', audio: 'Audio', document: 'Document', text: 'Text', link: 'Link', quiz: 'Quiz' }
export const KIND_ICON: Record<LessonKind, LucideIcon> = { video: Video, audio: Headphones, document: FileText, text: AlignLeft, link: Link2, quiz: ListChecks }

/** The file types each kind of lesson takes; the server checks the real contents too. */
export const FILE_ACCEPT: Record<'video' | 'audio' | 'document', string> = {
  video: '.mp4,.m4v,.mov,.webm',
  audio: '.mp3,.m4a,.wav,.ogg',
  document: '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.txt,.png,.jpg,.jpeg,.webp',
}

export const takesFile = (kind: LessonKind): kind is 'video' | 'audio' | 'document' => kind === 'video' || kind === 'audio' || kind === 'document'

export interface Media { original: string | null; type: string | null; size: number | null; inline?: boolean }

export interface CourseSummary {
  assignment_id: number
  course_id: number
  title: string
  description: string | null
  category: string | null
  lessons: number
  done: number
  percent: number
  status: 'not_started' | 'in_progress' | 'completed'
  overdue: boolean
  due_on: string | null
  assigned_at: string
  started_at: string | null
  completed_at: string | null
  score: number | null
  certificate: boolean
}

export interface PlayerLesson {
  id: number
  title: string
  kind: LessonKind
  body: string | null
  external_url: string | null
  media: Media | null
  completed: boolean
  position_seconds: number
  questions: number
}

export interface CourseDetail extends CourseSummary {
  pass_mark: number
  lesson_list: PlayerLesson[]
}

export function fileSize(bytes: number | null | undefined): string {
  if (!bytes) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export const STATUS_LABEL = { not_started: 'Not started', in_progress: 'In progress', completed: 'Completed' } as const

export interface AdminQuestion { id: number; text: string; options: string[]; correct: number }

export interface AdminLesson {
  id: number
  position: number
  title: string
  kind: LessonKind
  body: string | null
  external_url: string | null
  media: Media | null
  slides: Slide[]
  video: VideoState
  questions: AdminQuestion[]
}

export interface CourseRow {
  id: number
  title: string
  description: string | null
  category: string | null
  status: 'draft' | 'published'
  pass_mark: number
  certificate: boolean
  lessons: number
  assigned: number
  completed: number
}

export interface AdminCourse extends Omit<CourseRow, 'lessons' | 'assigned' | 'completed'> {
  problems: string[]
  lesson_list: AdminLesson[]
}

export interface ProgressRow {
  assignment_id: number
  course_id: number
  course: string
  employee: string
  employee_code: string
  job_title: string
  locations: string[]
  status: 'not_started' | 'in_progress' | 'completed'
  overdue: boolean
  lessons: number
  done: number
  percent: number
  due_on: string | null
  last_activity: string | null
  completed_at: string | null
  score: number | null
  certificate_no: string | null
}

export type VoiceKind = 'none' | 'typed' | 'upload'

/** One slide of a video made from slides; the picture and recording are shown by their file names. */
export interface Slide {
  id: string
  title: string
  bullets: string[]
  narration: string | null
  voice: VoiceKind
  seconds: number
  image: string | null
  audio: string | null
}

export interface VideoState {
  status: 'queued' | 'rendering' | 'ready' | 'outdated' | 'failed' | null
  error: string | null
}

export const VIDEO_STATUS_LABEL = {
  queued: 'Waiting to be made', rendering: 'Being made', ready: 'Video ready', outdated: 'Slides changed since the video was made', failed: 'The video could not be made',
} as const

export const isMaking = (video: VideoState) => video.status === 'queued' || video.status === 'rendering'
