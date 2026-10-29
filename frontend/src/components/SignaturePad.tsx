import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'

interface SignaturePadProps {
  /** Called with the drawn signature as a PNG, or null once it is cleared. */
  onChange: (png: Blob | null) => void
}

/** A box to sign in with a finger, a stylus or the mouse. */
export function SignaturePad({ onChange }: SignaturePadProps) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const drawing = useRef(false)
  const [signed, setSigned] = useState(false)

  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return
    ctx.lineWidth = 2.5
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.strokeStyle = '#0f172a'
  }, [])

  function point(event: React.PointerEvent<HTMLCanvasElement>) {
    const box = event.currentTarget.getBoundingClientRect()
    return { x: ((event.clientX - box.left) / box.width) * event.currentTarget.width, y: ((event.clientY - box.top) / box.height) * event.currentTarget.height }
  }

  function start(event: React.PointerEvent<HTMLCanvasElement>) {
    const ctx = event.currentTarget.getContext('2d')
    if (!ctx) return
    event.currentTarget.setPointerCapture(event.pointerId)
    drawing.current = true
    const { x, y } = point(event)
    ctx.beginPath()
    ctx.moveTo(x, y)
  }

  function move(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return
    const ctx = event.currentTarget.getContext('2d')
    const { x, y } = point(event)
    ctx?.lineTo(x, y)
    ctx?.stroke()
  }

  function end() {
    if (!drawing.current) return
    drawing.current = false
    setSigned(true)
    canvas.current?.toBlob((blob) => onChange(blob), 'image/png')
  }

  function clear() {
    const el = canvas.current
    el?.getContext('2d')?.clearRect(0, 0, el.width, el.height)
    setSigned(false)
    onChange(null)
  }

  return (
    <div className="space-y-2">
      <canvas
        ref={canvas}
        width={600}
        height={200}
        role="img"
        aria-label="Signature box"
        className="h-32 w-full max-w-md touch-none rounded-lg border border-dashed border-border-strong bg-white"
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
      />
      <div className="flex items-center gap-3 text-xs text-ink-muted">
        <span>{signed ? 'Signature captured' : 'Sign inside the box'}</span>
        {signed && <Button type="button" size="sm" variant="ghost" onClick={clear}>Clear</Button>}
      </div>
    </div>
  )
}
