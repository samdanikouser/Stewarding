import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/modal'
import { tokenStore } from '@/lib/api'

interface Props {
  recordId: number
  which: 'in' | 'out'
  who?: string
}

/** The photo kept with a face check-in or check-out, fetched with the sign-in token because it is not public. */
export function FaceSnapshotButton({ recordId, which, who }: Props) {
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!open) return
    let revoked = false
    let made: string | null = null
    fetch(`/api/attendance/${recordId}/snapshot/${which}`, { headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error('missing'))))
      .then((blob) => {
        if (revoked) return
        made = URL.createObjectURL(blob)
        setUrl(made)
      })
      .catch(() => setFailed(true))
    return () => {
      revoked = true
      if (made) URL.revokeObjectURL(made)
      setUrl(null)
      setFailed(false)
    }
  }, [open, recordId, which])

  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>Face {which}</Button>
      <Modal open={open} title={`Face check-${which}${who ? ` - ${who}` : ''}`} onClose={() => setOpen(false)}>
        {url && <img src={url} alt={`Face at check-${which}`} className="mx-auto max-h-[60vh] w-auto rounded-lg border border-border" />}
        {failed && <p className="text-sm text-ink-muted">No snapshot was kept for this record, or it has passed its retention period.</p>}
        {!url && !failed && <p className="text-sm text-ink-muted">Loading the photo</p>}
        <p className="mt-3 text-xs text-ink-muted">Viewing a snapshot is recorded in the audit log.</p>
      </Modal>
    </>
  )
}
