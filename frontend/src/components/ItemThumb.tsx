import { Package } from 'lucide-react'
import { useEffect, useState } from 'react'
import { tokenStore } from '@/lib/api'
import { cn } from '@/lib/utils'

const loaded = new Map<string, Promise<string>>()

function thumbUrl(name: string): Promise<string> {
  let found = loaded.get(name)
  if (!found) {
    found = fetch(`/api/uploads/${name}`, { headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error('missing'))))
      .then((blob) => URL.createObjectURL(blob))
    found.catch(() => loaded.delete(name))
    loaded.set(name, found)
  }
  return found
}

/** An item's thumbnail, or a plain tile when it has none; the size comes from `className`. */
export function ItemThumb({ path, name, className }: { path: string | null; name: string; className?: string }) {
  const [url, setUrl] = useState<{ path: string; src: string } | null>(null)
  useEffect(() => {
    if (!path) return
    let live = true
    thumbUrl(path).then((src) => live && setUrl({ path, src }), () => undefined)
    return () => {
      live = false
    }
  }, [path])

  const shown = url && url.path === path ? url.src : null
  return (
    <span className={cn('flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-surface-muted text-ink-muted', className)}>
      {shown ? <img src={shown} alt={name} loading="lazy" className="h-full w-full object-cover" /> : <Package aria-hidden className="h-1/2 w-1/2" />}
    </span>
  )
}
