import { Printer } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/table'
import { useApi } from '@/lib/useApi'
import { SettingsRules } from '@/pages/settings/SettingsRules'

interface Code {
  kind: 'equipment' | 'location'
  id: number
  name: string
  location_name: string
  svg: string
}

function Label({ code }: { code: Code }) {
  return (
    <li className="flex break-inside-avoid flex-col items-center gap-1 rounded-xl border border-border bg-white p-3 text-center text-black">
      <img alt={`QR code for ${code.name}`} width={140} height={140} src={`data:image/svg+xml;utf8,${encodeURIComponent(code.svg)}`} />
      <p className="text-sm font-semibold">{code.name}</p>
      {code.kind === 'equipment' && <p className="text-xs">{code.location_name}</p>}
    </li>
  )
}

/** The rules for requiring a scan, and the QR code of every location and monitoring point to print and post. */
export function SettingsQrCodes() {
  const { data } = useApi<{ locations: Code[]; points: Code[] }>(`/scan/codes?base=${encodeURIComponent(window.location.origin)}`)
  return (
    <div className="space-y-6">
      <SettingsRules section="qr-codes" />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Codes to print</h2>
          <p className="text-sm text-ink-muted">Post a location code where checklists are done and a point code on each fridge, oven or station.</p>
        </div>
        <Button variant="outline" onClick={() => window.print()}><Printer aria-hidden className="mr-2 h-4 w-4" />Print</Button>
      </div>
      {!data ? <Skeleton className="h-40 w-full" /> : (
        <Card>
          <CardContent className="print-sheet space-y-5 py-5">
            <section aria-label="Location codes" className="space-y-2">
              <h3 className="font-semibold">Locations</h3>
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{data.locations.map((c) => <Label key={`l${c.id}`} code={c} />)}</ul>
            </section>
            <section aria-label="Monitoring point codes" className="space-y-2">
              <h3 className="font-semibold">Monitoring points</h3>
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{data.points.map((c) => <Label key={`e${c.id}`} code={c} />)}</ul>
            </section>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
