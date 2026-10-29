import { ArrowDown, ArrowUp, Clapperboard, Copy, ImagePlus, Keyboard, Loader2, Mic, Play, Plus, Trash2, Upload, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { ProgressBar } from '@/components/ProgressBar'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Skeleton } from '@/components/ui/table'
import { api, tokenStore } from '@/lib/api'
import { VIDEO_STATUS_LABEL, isMaking, type AdminCourse, type AdminLesson, type Slide, type VoiceKind } from '@/lib/training'
import { useRun } from '@/lib/toast'
import { uploadWithProgress } from '@/lib/uploadProgress'
import { useApi } from '@/lib/useApi'
import { MediaPreview } from '@/pages/training/MediaPreview'

const TEXTAREA = 'w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm placeholder:text-ink-muted focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-60'

interface Draft {
  key: number
  id: string | null
  title: string
  bulletsText: string
  narration: string
  voice: VoiceKind
  seconds: string
  image: string | null
  audio: string | null
}

let counter = 0
const blank = (title = ''): Draft => ({ key: ++counter, id: null, title, bulletsText: '', narration: '', voice: 'none', seconds: '6', image: null, audio: null })
const toDraft = (s: Slide): Draft => ({ key: ++counter, id: s.id, title: s.title, bulletsText: s.bullets.join('\n'), narration: s.narration ?? '', voice: s.voice, seconds: String(s.seconds), image: s.image, audio: s.audio })
/** One line per point, with a line over the server's 160-character limit cut at a word instead of being refused. */
const toPoints = (text: string) => text.split('\n').flatMap((line) => line.trim().match(/.{1,160}(?:\s|$)|\S{1,160}/g) ?? []).map((b) => b.trim()).filter(Boolean)
const toBody = (d: Draft) => ({
  id: d.id, title: d.title, bullets: toPoints(d.bulletsText), narration: d.narration.trim() || null, voice: d.voice,
  seconds: Math.min(120, Math.max(2, Number(d.seconds) || 6)),
})

/** The slide as it will look in the video, drawn by the server so what is previewed is what is made. */
function SlidePreview({ lessonId, slideId, version }: { lessonId: number; slideId: string; version: number }) {
  const [shown, setShown] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let live = true
    let made: string | null = null
    fetch(`/api/training/lessons/${lessonId}/slides/${slideId}/preview.png?v=${version}`, { headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error('preview'))))
      .then((blob) => {
        if (!live) return
        made = URL.createObjectURL(blob)
        setShown(made)
        setFailed(false)
      })
      .catch(() => live && setFailed(true))
    return () => {
      live = false
      if (made) URL.revokeObjectURL(made)
    }
  }, [lessonId, slideId, version])

  if (failed) return <div className="flex aspect-video items-center justify-center rounded-xl border border-dashed border-border text-sm text-ink-muted">The preview could not be drawn</div>
  if (!shown) return <Skeleton className="aspect-video w-full" />
  return <img src={shown} alt="How this slide will look in the video" className="aspect-video w-full rounded-xl border border-border bg-black object-contain shadow-sm" />
}

interface EditorProps {
  lesson: AdminLesson
  typedVoice: boolean
  refresh: () => void
  onClose: () => void
}

function Editor({ lesson, typedVoice, refresh, onClose }: EditorProps) {
  const run = useRun()
  const [slides, setSlides] = useState<Draft[]>(() => (lesson.slides.length ? lesson.slides.map(toDraft) : [blank(lesson.title)]))
  const [at, setAt] = useState(0)
  const [dirty, setDirty] = useState(lesson.slides.length === 0)
  const [version, setVersion] = useState(0)
  const [progress, setProgress] = useState<number | null>(null)
  const [watching, setWatching] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [silent, setSilent] = useState(false)
  const picture = useRef<HTMLInputElement>(null)
  const recording = useRef<HTMLInputElement>(null)

  const index = Math.min(at, slides.length - 1)
  const slide = slides[index]
  const making = isMaking(lesson.video)
  const locked = making || progress !== null

  const edit = (patch: Partial<Draft>) => {
    setSlides((all) => all.map((s, i) => (i === index ? { ...s, ...patch } : s)))
    setDirty(true)
  }
  const arrange = (next: Draft[], select: number) => {
    setSlides(next)
    setAt(select)
    setDirty(true)
  }
  const adopt = (saved: Slide[]) => setSlides((all) => all.map((s, i) => (saved[i] ? { ...s, id: saved[i].id, image: saved[i].image, audio: saved[i].audio, voice: saved[i].voice } : s)))

  async function save(): Promise<Slide[] | null> {
    let saved: Slide[] | null = null
    const ok = await run(async () => {
      saved = (await api<AdminLesson>(`/training/lessons/${lesson.id}/slides`, { method: 'PUT', body: { slides: slides.map(toBody) } })).slides
    })
    if (!ok || !saved) return null
    adopt(saved)
    setDirty(false)
    setVersion((v) => v + 1)
    refresh()
    return saved
  }

  async function attach(kind: 'image' | 'audio', file: File) {
    const saved = dirty || !slide.id ? await save() : null
    const id = saved ? saved[index]?.id : slide.id
    if (!id) return
    setProgress(0)
    let result: AdminLesson | null = null
    const ok = await run(async () => {
      result = await uploadWithProgress<AdminLesson>(`/training/lessons/${lesson.id}/slides/${id}/${kind}`, file, setProgress)
    }, kind === 'image' ? 'Picture added' : 'Recording added')
    setProgress(null)
    if (ok && result) {
      adopt((result as AdminLesson).slides)
      setVersion((v) => v + 1)
      refresh()
    }
  }

  async function detach(kind: 'image' | 'audio') {
    const saved = dirty ? await save() : null
    const id = saved ? saved[index]?.id : slide.id
    if (!id) return
    let result: AdminLesson | null = null
    const ok = await run(async () => {
      result = await api<AdminLesson>(`/training/lessons/${lesson.id}/slides/${id}/${kind}`, { method: 'DELETE' })
    }, kind === 'image' ? 'Picture removed' : 'Recording removed')
    if (ok && result) {
      adopt((result as AdminLesson).slides)
      setVersion((v) => v + 1)
      refresh()
    }
  }

  const voiced = slides.filter((s) => s.voice !== 'none').length

  async function make(sure = false) {
    if (!sure && voiced === 0) return setSilent(true)  // nothing would be heard: check that is meant
    if (dirty && !(await save())) return
    if (await run(() => api(`/training/lessons/${lesson.id}/render`, { method: 'POST' }), 'Making the video. This takes a few minutes; you can close this window.')) refresh()
  }

  const close = () => (dirty && !making ? setLeaving(true) : onClose())
  const status = lesson.video.status

  return (
    <>
      <Modal open={!watching && !leaving && !silent} size="xl" title={`Video from slides: ${lesson.title}`} onClose={close}
        description="Write each slide, add a picture if it helps, and choose how it is narrated. The video is made from the slides in order."
        footer={<>
          <Button type="button" variant="outline" onClick={close}>Close</Button>
          <Button type="button" variant="outline" disabled={!dirty || locked} onClick={save}>Save slides</Button>
          <Button type="button" disabled={locked} onClick={() => make()}><Clapperboard className="h-4 w-4" /> {status === 'ready' || status === 'outdated' ? 'Make the video again' : 'Make the video'}</Button>
        </>}>
        <div className="space-y-5">
          <p className={`text-sm ${voiced === 0 ? 'font-medium text-warn' : 'text-ink-muted'}`}>
            {voiced === 0 ? 'No slide has a voice-over yet, so the video will have no sound.' : `Voice-over on ${voiced} of ${slides.length} ${slides.length === 1 ? 'slide' : 'slides'}; the others are silent.`}
          </p>
          {status && (
            <div role="status" className={`flex flex-wrap items-center gap-3 rounded-xl p-3 text-sm ${status === 'failed' ? 'bg-danger-soft text-danger' : status === 'ready' ? 'bg-ok-soft text-ok' : 'bg-warn-soft text-warn'}`}>
              {making && <Loader2 aria-hidden className="h-4 w-4 animate-spin" />}
              <span className="flex-1">{VIDEO_STATUS_LABEL[status]}{status === 'failed' && lesson.video.error ? `: ${lesson.video.error}` : ''}{making ? '. This page updates by itself.' : ''}</span>
              {(status === 'ready' || status === 'outdated') && lesson.media && <Button type="button" size="sm" variant="outline" onClick={() => setWatching(true)}><Play className="h-3.5 w-3.5" /> Watch it</Button>}
            </div>
          )}

          <div className="grid gap-5 lg:grid-cols-[15rem_1fr]">
            <div className="space-y-3">
              <ol aria-label="Slides" className="space-y-1.5">
                {slides.map((s, position) => (
                  <li key={s.key}>
                    <button type="button" aria-current={position === index ? 'true' : undefined} onClick={() => setAt(position)}
                      className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm ${position === index ? 'border-brand bg-brand-soft font-medium' : 'border-border bg-surface hover:bg-surface-muted'}`}>
                      <span className="w-5 shrink-0 text-ink-muted">{position + 1}</span>
                      <span className="min-w-0 flex-1 truncate">{s.title || 'Untitled slide'}</span>
                      {s.image && <ImagePlus aria-label="Has a picture" className="h-3.5 w-3.5 shrink-0 text-ink-muted" />}
                      {s.voice === 'typed' && <Keyboard aria-label="Typed voice-over" className="h-3.5 w-3.5 shrink-0 text-ink-muted" />}
                      {s.voice === 'upload' && <Mic aria-label="Recorded voice-over" className="h-3.5 w-3.5 shrink-0 text-ink-muted" />}
                    </button>
                  </li>
                ))}
              </ol>
              <div className="flex flex-wrap gap-1.5">
                <Button type="button" size="sm" disabled={locked || slides.length >= 40} onClick={() => arrange([...slides, blank()], slides.length)}><Plus className="h-3.5 w-3.5" /> Add slide</Button>
                <Button type="button" size="sm" variant="outline" disabled={locked || slides.length >= 40} aria-label="Copy this slide"
                  onClick={() => arrange([...slides.slice(0, index + 1), { ...slide, key: ++counter, id: null, image: null, audio: null, voice: slide.voice === 'upload' ? 'none' : slide.voice }, ...slides.slice(index + 1)], index + 1)}><Copy className="h-3.5 w-3.5" /></Button>
                <Button type="button" size="sm" variant="outline" disabled={locked || index === 0} aria-label="Move this slide up"
                  onClick={() => arrange(slides.map((s, i) => (i === index - 1 ? slide : i === index ? slides[index - 1] : s)), index - 1)}><ArrowUp className="h-3.5 w-3.5" /></Button>
                <Button type="button" size="sm" variant="outline" disabled={locked || index === slides.length - 1} aria-label="Move this slide down"
                  onClick={() => arrange(slides.map((s, i) => (i === index + 1 ? slide : i === index ? slides[index + 1] : s)), index + 1)}><ArrowDown className="h-3.5 w-3.5" /></Button>
                <Button type="button" size="sm" variant="outline" className="border-danger/40 text-danger hover:bg-danger-soft" disabled={locked || slides.length === 1} aria-label="Delete this slide"
                  onClick={() => arrange(slides.filter((_, i) => i !== index), Math.max(0, index - 1))}><Trash2 className="h-3.5 w-3.5" /></Button>
              </div>
            </div>

            <div className="grid gap-5 xl:grid-cols-2">
              <fieldset disabled={locked} className="space-y-4">
                <Field label="Slide title"><Input maxLength={120} value={slide.title} onChange={(e) => edit({ title: e.target.value })} /></Field>
                <Field label="Points (one per line)"><textarea className={TEXTAREA} rows={5} value={slide.bulletsText} onChange={(e) => edit({ bulletsText: e.target.value })} /></Field>

                <div className="space-y-1.5">
                  <p className="text-sm font-medium">Picture (optional)</p>
                  <input ref={picture} type="file" hidden accept=".png,.jpg,.jpeg,.webp" aria-label="Slide picture" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void attach('image', f) }} />
                  <div className="flex flex-wrap items-center gap-2">
                    <Button type="button" size="sm" variant="outline" onClick={() => picture.current?.click()}><ImagePlus className="h-3.5 w-3.5" /> {slide.image ? 'Replace picture' : 'Add a picture'}</Button>
                    {slide.image && <><span className="max-w-40 truncate text-sm text-ink-muted">{slide.image}</span><Button type="button" size="sm" variant="ghost" aria-label="Remove the picture" onClick={() => detach('image')}><X className="h-3.5 w-3.5" /></Button></>}
                  </div>
                </div>

                <fieldset className="space-y-2">
                  <legend className="text-sm font-medium">Voice-over</legend>
                  <label className="flex items-center gap-2 text-sm"><input type="radio" name="voice" checked={slide.voice === 'none'} onChange={() => edit({ voice: 'none' })} /> None; show the slide for a set time</label>
                  {slide.voice === 'none' && <div className="pl-6"><Field label="Seconds on screen"><Input type="number" min={2} max={120} className="w-28" value={slide.seconds} onChange={(e) => edit({ seconds: e.target.value })} /></Field></div>}
                  <label className={`flex items-center gap-2 text-sm ${typedVoice ? '' : 'text-ink-muted'}`}>
                    <input type="radio" name="voice" disabled={!typedVoice} checked={slide.voice === 'typed'} onChange={() => edit({ voice: 'typed' })} /> Type what is said; a computer voice reads it
                  </label>
                  {!typedVoice && <p className="pl-6 text-xs text-ink-muted">Not set up on this server yet. Upload a recording instead, or see the deployment notes to install a voice.</p>}
                  {slide.voice === 'typed' && <div className="pl-6"><textarea className={TEXTAREA} rows={4} maxLength={3000} aria-label="What is said" placeholder="Type exactly what should be said" value={slide.narration} onChange={(e) => edit({ narration: e.target.value })} /></div>}
                  <label className="flex items-center gap-2 text-sm"><input type="radio" name="voice" checked={slide.voice === 'upload'} onChange={() => edit({ voice: 'upload' })} /> Upload a recording</label>
                  {slide.voice === 'upload' && (
                    <div className="space-y-2 pl-6">
                      <input ref={recording} type="file" hidden accept=".mp3,.m4a,.wav,.ogg" aria-label="Voice-over recording" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void attach('audio', f) }} />
                      <div className="flex flex-wrap items-center gap-2">
                        <Button type="button" size="sm" variant="outline" onClick={() => recording.current?.click()}><Upload className="h-3.5 w-3.5" /> {slide.audio ? 'Replace recording' : 'Choose a recording'}</Button>
                        {slide.audio && <><span className="max-w-40 truncate text-sm text-ink-muted">{slide.audio}</span><Button type="button" size="sm" variant="ghost" aria-label="Remove the recording" onClick={() => detach('audio')}><X className="h-3.5 w-3.5" /></Button></>}
                      </div>
                      <p className="text-xs text-ink-muted">The slide stays up as long as the recording lasts.</p>
                    </div>
                  )}
                </fieldset>
              </fieldset>

              <div className="space-y-3">
                <p className="text-sm font-medium">Preview</p>
                {slide.id && !dirty ? <SlidePreview lessonId={lesson.id} slideId={slide.id} version={version} /> : (
                  <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border p-4 text-center text-sm text-ink-muted">
                    <p>Save the slides to see how this one will look.</p>
                    <Button type="button" size="sm" variant="outline" disabled={locked} onClick={save}>Save slides</Button>
                  </div>
                )}
                {progress !== null && (
                  <div className="space-y-1"><ProgressBar percent={progress} label="Uploading" /><p className="text-xs text-ink-muted">Uploading {progress}%</p></div>
                )}
              </div>
            </div>
          </div>
        </div>
      </Modal>

      {watching && <MediaPreview lessonId={lesson.id} title={lesson.title} onClose={() => setWatching(false)} />}
      <ConfirmDialog open={silent} title="Make a video with no sound?" confirmLabel="Make it without sound"
        message="None of the slides has a voice-over, so the video will be silent. To add sound, choose Upload a recording (or a typed voice) on the slides that should be spoken."
        onConfirm={() => { setSilent(false); void make(true) }} onCancel={() => setSilent(false)} />
      <ConfirmDialog open={leaving} title="Close without saving?" confirmLabel="Close without saving"
        message="You have changes to the slides that are not saved. If you close now they are lost."
        onConfirm={() => { setLeaving(false); onClose() }} onCancel={() => setLeaving(false)} />
    </>
  )
}

/** Makes a video lesson from slides: a title, points and picture per slide, and a typed or recorded voice-over. */
export function SlideVideoEditor({ courseId, lessonId, onClose, onChanged }: { courseId: number; lessonId: number; onClose: () => void; onChanged: () => void }) {
  const course = useApi<AdminCourse>(`/training/courses/${courseId}`)
  const voice = useApi<{ typed: boolean }>('/training/voice')
  const lesson = course.data?.lesson_list.find((l) => l.id === lessonId)
  const making = lesson ? isMaking(lesson.video) : false
  const was = useRef(false)
  const reload = course.reload

  useEffect(() => {
    if (!making) return
    const timer = setInterval(reload, 3000)
    return () => clearInterval(timer)
  }, [making, reload])

  useEffect(() => {
    if (was.current && !making) onChanged()
    was.current = making
  }, [making, onChanged])

  if (!course.data || !lesson) {
    return <Modal open size="xl" title="Video from slides" onClose={onClose}><Skeleton className="h-64 w-full" /></Modal>
  }
  return <Editor key={lesson.id} lesson={lesson} typedVoice={voice.data?.typed ?? false} refresh={reload} onClose={onClose} />
}
