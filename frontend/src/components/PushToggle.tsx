import { BellRing } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { currentSubscription, disablePush, enablePush, needsHomeScreen, pushSupported } from '@/lib/push'
import { useRun } from '@/lib/toast'

/** Turns pop-up alerts on or off for this browser or phone. */
export function PushToggle() {
  const run = useRun()
  const [on, setOn] = useState<boolean | null>(null)

  useEffect(() => {
    if (pushSupported()) currentSubscription().then((s) => setOn(s !== null), () => setOn(false))
  }, [])

  if (needsHomeScreen()) {
    return <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink-muted">To get alerts on an iPhone, tap Share, then Add to Home Screen, and open Plato from there.</p>
  }
  if (!pushSupported() || on === null) return null

  async function toggle() {
    const ok = await run(async () => { await (on ? disablePush() : enablePush()) }, on ? 'Alerts turned off on this device' : 'Alerts turned on for this device')
    if (ok) setOn(!on)
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface px-3 py-2 text-sm">
      <BellRing aria-hidden className="h-4 w-4" />
      <span>{on ? 'Alerts pop up on this device' : 'Get alerts as pop-ups on this device, even when Plato is closed'}</span>
      <Button size="sm" variant="outline" onClick={toggle}>{on ? 'Turn off' : 'Turn on'}</Button>
      {on && <Button size="sm" variant="outline" onClick={() => run(() => api('/push/test', { body: {} }), 'Test alert sent')}>Send a test</Button>}
    </div>
  )
}
