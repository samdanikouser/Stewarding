import { ArrowLeft, ArrowRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { advance, averageFace, faceDistance, loadFaceModels, snapshotOf, STEP_TEXT, yawRatio, type Step } from '@/lib/face'
import { cn } from '@/lib/utils'

export type FaceResult = { ok: true; message?: string } | { ok: false; message: string }

/** What the live check saw: the head turns that were shown, in order, and a small photo taken at the end. */
export interface FaceEvidence {
  liveness: Step[]
  snapshot: string | null
}

interface FaceCaptureProps {
  /** Called once the check is complete, with the face template; say whether it worked so the box can show it. */
  onCapture: (descriptor: number[], evidence: FaceEvidence) => Promise<FaceResult>
  /** The head turns to ask for, from the server; none means a plain steady-face capture, as when enrolling. */
  steps?: Step[]
}

const STEADY_FRAMES = 3
const STEADY_DISTANCE = 0.3
const SAME_PERSON = 0.45
const FRAME_MS = 300
const TURN_FRAME_MS = 120
const STEP_TIMEOUT_MS = 12000
const RETRY_MS = 2500

type Phase = 'starting' | 'looking' | 'turning' | 'checking' | 'ok' | 'failed' | 'blocked'
type Stage = 'anchor' | 'turns' | 'final'

/**
 * Shows the front camera with a box that follows the face. With head-turn steps it asks for each turn on the live
 * video, then a steady look at the camera that must be the same person as at the start, and takes a snapshot.
 * The camera and the model run in this browser; only the template, the turns and one small photo leave it.
 */
export function FaceCapture({ onCapture, steps }: FaceCaptureProps) {
  const video = useRef<HTMLVideoElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const [phase, setPhase] = useState<Phase>('starting')
  const [message, setMessage] = useState('Starting the camera')
  const [progress, setProgress] = useState({ done: 0, current: null as Step | null })
  const capture = useRef(onCapture)
  const plan = useRef(steps)
  useEffect(() => {
    capture.current = onCapture
    plan.current = steps
  })

  useEffect(() => {
    let stopped = false
    let stream: MediaStream | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let recent: Float32Array[] = []
    let anchor: number[] | null = null
    let stage: Stage = plan.current?.length ? 'anchor' : 'final'
    let index = 0
    let turned = false
    let stepStarted = 0

    const show = (next: Phase, text: string) => {
      if (stopped) return
      setPhase(next)
      setMessage(text)
    }
    const restart = () => {
      recent = []
      anchor = null
      index = 0
      turned = false
      stage = plan.current?.length ? 'anchor' : 'final'
      setProgress({ done: 0, current: null })
    }
    const ask = (sequence: Step[]) => {
      stepStarted = Date.now()
      setProgress({ done: index, current: sequence[index] })
      show('turning', `Step ${index + 1} of ${sequence.length}: ${STEP_TEXT[sequence[index]]}`)
    }

    async function run() {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('camera-unavailable')
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
        if (stopped || !video.current) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        video.current.srcObject = stream
        await video.current.play()
        show('starting', 'Loading the face model')
        const faceapi = await loadFaceModels()
        const options = new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 })
        show('looking', 'Look at the camera')

        const draw = (box: { x: number; y: number; width: number; height: number } | null, colour: string) => {
          const canvas = overlay.current
          const context = canvas?.getContext('2d')
          if (!canvas || !context || !video.current) return
          canvas.width = video.current.videoWidth
          canvas.height = video.current.videoHeight
          context.clearRect(0, 0, canvas.width, canvas.height)
          if (box) {
            context.lineWidth = 4
            context.strokeStyle = colour
            context.strokeRect(box.x, box.y, box.width, box.height)
          }
        }

        const tick = async () => {
          if (stopped || !video.current) return
          const sequence = plan.current ?? []

          if (stage === 'turns') {
            const seen = await faceapi.detectSingleFace(video.current, options).withFaceLandmarks(true)
            draw(seen?.detection.box ?? null, '#facc15')
            if (!seen) {
              restart()
              show('looking', 'Look at the camera to start again')
              timer = setTimeout(tick, FRAME_MS)
              return
            }
            const next = advance(sequence[index], yawRatio(seen.landmarks.positions), turned)
            turned = next.turned
            if (next.done) {
              index += 1
              turned = false
              if (index >= sequence.length) {
                stage = 'final'
                recent = []
                setProgress({ done: index, current: null })
                show('looking', 'Now look straight at the camera')
              } else {
                ask(sequence)
              }
            } else if (Date.now() - stepStarted > STEP_TIMEOUT_MS) {
              restart()
              show('failed', 'That took too long. Look at the camera to start again')
              timer = setTimeout(tick, RETRY_MS)
              return
            }
            timer = setTimeout(tick, TURN_FRAME_MS)
            return
          }

          const found = await faceapi.detectSingleFace(video.current, options).withFaceLandmarks(true).withFaceDescriptor()
          draw(found?.detection.box ?? null, recent.length >= STEADY_FRAMES - 1 ? '#16a34a' : '#facc15')
          if (!found) {
            recent = []
            show('looking', stage === 'final' && sequence.length ? 'Now look straight at the camera' : 'Look at the camera')
            timer = setTimeout(tick, FRAME_MS)
            return
          }
          const last = recent[recent.length - 1]
          recent = last && faceDistance(last, found.descriptor) > STEADY_DISTANCE ? [found.descriptor] : [...recent, found.descriptor]
          if (recent.length < STEADY_FRAMES) {
            show('looking', 'Hold still')
            timer = setTimeout(tick, FRAME_MS)
            return
          }
          const template = averageFace(recent)
          recent = []
          if (stage === 'anchor') {
            anchor = template
            stage = 'turns'
            index = 0
            turned = false
            ask(sequence)
            timer = setTimeout(tick, TURN_FRAME_MS)
            return
          }
          if (anchor && faceDistance(anchor, template) > SAME_PERSON) {
            restart()
            show('failed', 'The face changed during the check. Start again')
            timer = setTimeout(tick, RETRY_MS)
            return
          }
          show('checking', 'Checking your face')
          const result = await capture.current(template, { liveness: sequence, snapshot: sequence.length ? snapshotOf(video.current) : null })
          if (result.ok) {
            show('ok', result.message ?? 'Match found!')
            return
          }
          restart()
          show('failed', result.message)
          timer = setTimeout(tick, RETRY_MS)
        }
        void tick()
      } catch (err) {
        const denied = err instanceof DOMException && err.name === 'NotAllowedError'
        show('blocked', denied ? 'Allow camera access in your browser, then open this again'
          : err instanceof Error && err.message === 'camera-unavailable' ? 'Camera access needs a secure (https) page'
            : 'The camera or the face model could not start')
      }
    }

    void run()
    return () => {
      stopped = true
      clearTimeout(timer)
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  const total = steps?.length ?? 0
  return (
    <div className="space-y-3">
      <div className="relative mx-auto aspect-[4/3] w-full max-w-sm overflow-hidden rounded-xl bg-black">
        <video ref={video} muted playsInline className="h-full w-full -scale-x-100 object-cover" />
        <canvas ref={overlay} aria-hidden className="absolute inset-0 h-full w-full -scale-x-100 object-cover" />
        {progress.current && (
          <span aria-hidden className={cn('absolute top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-2 text-white', progress.current === 'turn_left' ? 'left-3' : 'right-3')}>
            {progress.current === 'turn_left' ? <ArrowLeft className="h-8 w-8" /> : <ArrowRight className="h-8 w-8" />}
          </span>
        )}
      </div>
      {total > 0 && (
        <div className="flex justify-center gap-2" aria-hidden>
          {Array.from({ length: total }, (_, i) => <span key={i} className={cn('h-2 w-8 rounded-full', i < progress.done ? 'bg-ok' : 'bg-border')} />)}
        </div>
      )}
      <p role="status" className={cn('text-center text-sm font-medium', phase === 'ok' && 'text-ok', (phase === 'failed' || phase === 'blocked') && 'text-danger')}>{message}</p>
    </div>
  )
}
