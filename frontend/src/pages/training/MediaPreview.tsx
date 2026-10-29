import { Download, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/modal'
import { Skeleton } from '@/components/ui/table'
import { useApi } from '@/lib/useApi'

interface MediaLink {
  url: string
  original: string
  type: string
  inline: boolean
}

/** Lets a manager watch, listen to or open a lesson's file, to check it before staff see it. */
export function MediaPreview({ lessonId, title, onClose }: { lessonId: number; title: string; onClose: () => void }) {
  const link = useApi<MediaLink>(`/training/lessons/${lessonId}/media-url`)
  const media = link.data

  return (
    <Modal open size="lg" title={title} onClose={onClose}>
      {link.error ? <p role="alert" className="text-sm text-danger">{link.error}</p> : !media ? <Skeleton className="aspect-video w-full" /> : (
        media.type.startsWith('video/') ? (
          <video src={media.url} controls autoPlay playsInline className="aspect-video w-full rounded-xl bg-black">Your browser cannot play this video.</video>
        ) : media.type.startsWith('audio/') ? (
          <audio src={media.url} controls autoPlay className="w-full">Your browser cannot play this audio.</audio>
        ) : (
          <div className="space-y-4">
            {media.type.startsWith('image/') && <img src={media.url} alt={media.original} className="max-h-[28rem] w-full rounded-lg object-contain" />}
            <p className="text-sm font-medium">{media.original}</p>
            <div className="flex gap-2">
              {media.inline && !media.type.startsWith('image/') && <Button asChild><a href={media.url} target="_blank" rel="noopener noreferrer"><ExternalLink className="h-4 w-4" /> Open</a></Button>}
              <Button asChild variant="outline"><a href={media.url} download={media.original}><Download className="h-4 w-4" /> Download</a></Button>
            </div>
          </div>
        )
      )}
    </Modal>
  )
}
