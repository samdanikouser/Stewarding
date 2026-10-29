import { useEffect, useRef, useState } from 'react'
import { Modal } from '@/components/ui/modal'
import { decodeQr } from '@/lib/qr'

interface Detector {
  detect: (source: CanvasImageSource) => Promise<{ rawValue: string }[]>
}

interface Props {
  open: boolean
  onClose: () => void
  onScan: (code: string) => void
  title?: string
  what?: string
}

/** The camera view; mounted only while the dialog is open, so every scan starts fresh and the camera is released on close. */
function Camera({ onScan, what }: { onScan: (code: string) => void; what: string }) {
  const video = useRef<HTMLVideoElement>(null)
  const found = useRef(onScan)
  const [message, setMessage] = useState('Starting the camera')
  useEffect(() => {
    found.current = onScan
  })

  useEffect(() => {
    let stopped = false
    let stream: MediaStream | null = null
    let timer: ReturnType<typeof setTimeout> | undefined

    async function run() {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('camera-unavailable')
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
        if (stopped || !video.current) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        video.current.srcObject = stream
        await video.current.play()
        setMessage('Point the camera at the QR code')
        const Native = (window as unknown as { BarcodeDetector?: new (options: { formats: string[] }) => Detector }).BarcodeDetector
        let detector: Detector | null = null
        try {
          detector = Native ? new Native({ formats: ['qr_code'] }) : null
        } catch {
          detector = null
        }
        const canvas = document.createElement('canvas')

        const look = async () => {
          if (stopped || !video.current) return
          // some browsers have a built-in detector that cannot read QR codes, so the decoder always gets a try on the same frame
          let text: string | null = detector ? ((await detector.detect(video.current).catch(() => []))[0]?.rawValue ?? null) : null
          if (!text && video.current.videoWidth) {
            canvas.width = video.current.videoWidth
            canvas.height = video.current.videoHeight
            const context = canvas.getContext('2d', { willReadFrequently: true })
            context?.drawImage(video.current, 0, 0)
            const image = context?.getImageData(0, 0, canvas.width, canvas.height)
            text = image ? decodeQr(image) : null
          }
          if (text) {
            found.current(text.trim())
            return
          }
          timer = setTimeout(look, 250)
        }
        void look()
      } catch (err) {
        const denied = err instanceof DOMException && err.name === 'NotAllowedError'
        setMessage(denied ? `Allow camera access in your browser, or type the ${what} instead`
          : err instanceof Error && err.message === 'camera-unavailable' ? `Camera access needs a secure (https) page. Type the ${what} instead`
            : `The camera could not start. Type the ${what} instead`)
      }
    }

    void run()
    return () => {
      stopped = true
      clearTimeout(timer)
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [what])

  return (
    <>
      <div className="relative mx-auto aspect-[4/3] w-full max-w-sm overflow-hidden rounded-xl bg-black">
        <video ref={video} muted playsInline className="h-full w-full object-cover" />
        <span aria-hidden className="absolute inset-8 rounded-lg border-2 border-white/70" />
      </div>
      <p role="status" className="mt-3 text-center text-sm font-medium">{message}</p>
    </>
  )
}

/** Reads a QR label with the back camera: the browser's own detector where there is one, otherwise a small decoder. */
export function LotScanner({ open, onClose, onScan, title = 'Scan a lot label', what = 'lot code' }: Props) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      {open && <Camera onScan={onScan} what={what} />}
    </Modal>
  )
}
