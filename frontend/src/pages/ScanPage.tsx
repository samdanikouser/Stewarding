import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/table'
import { api } from '@/lib/api'
import { ScanSummary } from '@/pages/ScanSummary'

interface Place {
  kind: 'equipment' | 'location'
  id: number
  name: string
  location_id: number
  location_name: string
}

/** Where a scanned QR code lands: it confirms the place and opens the matching form there. */
export function ScanPage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const asked = useRef(false)
  const [place, setPlace] = useState<Place | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (asked.current) return
    asked.current = true
    api<Place>('/scan', { body: { token } }).then(setPlace, (err: unknown) => setError(err instanceof Error ? err.message : 'This QR code could not be read'))
  }, [token])

  const isPoint = place?.kind === 'equipment'
  const go = (path: string) => place && navigate(path, { state: { locationId: place.location_id, equipmentId: isPoint ? place.id : undefined } })

  return (
    <div className="mx-auto max-w-md space-y-4">
      <h1 className="text-2xl font-semibold">QR code</h1>
      {error ? (
        <Card><CardContent className="space-y-3 py-5">
          <p role="alert" className="font-medium text-danger">{error}</p>
          <Link to="/" className="text-sm font-medium text-brand-deep hover:underline">Back to the dashboard</Link>
        </CardContent></Card>
      ) : !place ? <Skeleton className="h-32 w-full" /> : (
        <Card><CardContent className="space-y-4 py-5">
          <div>
            <p className="text-sm text-ink-muted">{isPoint ? 'Monitoring point' : 'Location'} scanned</p>
            <p className="text-xl font-semibold">{place.name}</p>
            {isPoint && <p className="text-sm text-ink-muted">{place.location_name}</p>}
          </div>
          {isPoint ? <Button className="h-12 w-full text-base" onClick={() => go('/monitoring')}>Record a check</Button> : (
            <div className="space-y-2">
              <Button className="h-12 w-full text-base" onClick={() => go('/checklists')}>Open today's checklists</Button>
              <Button variant="outline" className="h-12 w-full text-base" onClick={() => go('/monitoring')}>Open monitoring logs</Button>
            </div>
          )}
        </CardContent></Card>
      )}
      {place && <ScanSummary locationId={place.location_id} />}
    </div>
  )
}
