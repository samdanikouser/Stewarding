import { ArrowLeft, Printer } from 'lucide-react'
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ItemThumb } from '@/components/ItemThumb'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Skeleton, Table, Td, Th } from '@/components/ui/table'
import { api } from '@/lib/api'
import { fmtDateTime } from '@/lib/format'
import { useRun } from '@/lib/toast'
import { qs, useApi } from '@/lib/useApi'

interface Row {
  item_id: number
  code: string
  name: string
  image_path: string | null
  unit: string | null
  category: string | null
  storage_location: string | null
  qty: number | null
  reason: string
  others: number
  received: number
  book: number
  allowance: number
  here: number
}

interface Sheet { status: string; round_status: string; items: Row[] }
interface Saved { saved: number; refused: { item_id: number; message: string }[]; needs_reason: number[] }

/** Counting one location in a round: the number found, what others have counted, and how much is left to enter. */
export function RoundCountEntry({ roundId, locationId, locationName, onBack }: { roundId: number; locationId: number; locationName: string; onBack: () => void }) {
  const run = useRun()
  const sheet = useApi<Sheet>(`/rounds/${roundId}/entry${qs({ location_id: locationId })}`)
  const reloadSheet = sheet.reload
  const [typed, setTyped] = useState<Record<number, { qty: string; reason: string }>>({})
  const [dirty, setDirty] = useState<Set<number>>(new Set())
  const [problems, setProblems] = useState<Record<number, string>>({})
  const [saved, setSaved] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [onlyOpen, setOnlyOpen] = useState(false)
  const [showPictures, setShowPictures] = useState(true)
  const [showBooks, setShowBooks] = useState(true)  // turn off to count without seeing the system figure
  const loaded = useRef(false)

  useEffect(() => {
    if (!sheet.data || loaded.current) return
    loaded.current = true
    setTyped(Object.fromEntries(sheet.data.items.filter((i) => i.qty !== null).map((i) => [i.item_id, { qty: String(i.qty), reason: i.reason }])))
  }, [sheet.data])

  const finished = !!sheet.data && (sheet.data.status === 'done' || sheet.data.round_status !== 'counting')

  // Saving: what is typed goes to the server a moment after the last key, when you leave a box, or at once with the Save button, so the count
  // survives closing the page and can be reopened later. The page warns before it is left with anything unsaved.
  const [failed, setFailed] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const persist = useCallback(async (): Promise<boolean> => {
    if (dirty.size === 0 || finished) return true
    const entries = Object.fromEntries([...dirty].map((id) => [id, typed[id] ?? { qty: '', reason: '' }]))
    setSaving(true)
    try {
      const result = await api<Saved>(`/rounds/${roundId}/counts/${locationId}`, { method: 'PUT', body: { entries } })
      setProblems((all) => ({ ...Object.fromEntries(Object.entries(all).filter(([id]) => !(id in entries))), ...Object.fromEntries(result.refused.map((r) => [r.item_id, r.message])) }))
      setDirty(new Set())
      setFailed(null)
      setSaved(fmtDateTime(new Date().toISOString()))
      reloadSheet()  // what the others have counted may have changed meanwhile; what is typed here is kept
      return true
    } catch (err) {
      setFailed(err instanceof Error ? err.message : 'Could not save')  // the numbers stay on screen and are tried again
      return false
    } finally {
      setSaving(false)
    }
  }, [dirty, typed, roundId, locationId, finished, reloadSheet])

  useEffect(() => {
    if (dirty.size === 0 || finished) return
    const timer = setTimeout(persist, 800)
    return () => clearTimeout(timer)
  }, [dirty, typed, finished, persist])

  useEffect(() => {
    if (dirty.size === 0) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    const flush = () => { if (document.visibilityState === 'hidden') void persist() }
    window.addEventListener('beforeunload', warn)
    document.addEventListener('visibilitychange', flush)
    return () => {
      window.removeEventListener('beforeunload', warn)
      document.removeEventListener('visibilitychange', flush)
    }
  }, [dirty.size, persist])

  // other people are counting too, so "counted elsewhere" and "up to" are refreshed every half minute (typed numbers are never overwritten)
  useEffect(() => {
    if (finished) return
    const timer = setInterval(() => { if (dirty.size === 0 && document.visibilityState !== 'hidden') reloadSheet() }, 30_000)
    return () => clearInterval(timer)
  }, [finished, dirty.size, reloadSheet])

  const change = (id: number, patch: Partial<{ qty: string; reason: string }>) => {
    setTyped((all) => ({ ...all, [id]: { qty: all[id]?.qty ?? '', reason: all[id]?.reason ?? '', ...patch } }))
    setDirty((all) => new Set(all).add(id))
  }

  const categories = useMemo(() => [...new Set((sheet.data?.items ?? []).map((i) => i.category ?? ''))].filter(Boolean).sort(), [sheet.data])
  const shown = (sheet.data?.items ?? []).filter((i) => {
    if (category && i.category !== category) return false
    const words = search.toLowerCase().split(/\s+/).filter(Boolean)
    if (words.length && !words.every((w) => `${i.code} ${i.name}`.toLowerCase().includes(w))) return false
    return !onlyOpen || (typed[i.item_id]?.qty ?? '') === ''
  })
  const counted = Object.values(typed).filter((t) => t.qty !== '').length

  async function finish() {
    if (await run(() => api(`/rounds/${roundId}/counts/${locationId}/done`, { method: 'POST' }), `${locationName} is marked as counted`)) onBack()
  }

  async function reopen() {
    if (await run(() => api(`/rounds/${roundId}/counts/${locationId}/reopen`, { method: 'POST' }))) {
      loaded.current = false
      sheet.reload()
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Back to the round</Button>
        <h2 className="text-lg font-semibold">Counting {locationName}</h2>
        {finished && <Badge tone="ok">Finished</Badge>}
      </div>
      {!sheet.data ? <Skeleton className="h-48 w-full" /> : (
        <>
          <div className="filter-bar">
            <Input aria-label="Search items" className="w-56" placeholder="Search code or name" value={search} onChange={(e) => setSearch(e.target.value)} />
            <Select aria-label="Category" className="w-auto" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Not counted yet</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showPictures} onChange={(e) => setShowPictures(e.target.checked)} /> Show pictures</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showBooks} onChange={(e) => setShowBooks(e.target.checked)} /> Show the system stock here</label>
            <Button variant="outline" size="sm" onClick={() => window.open(`/count-sheet${qs({ location_id: locationId, all: 1 })}`, '_blank')}><Printer className="h-4 w-4" /> Print count sheet</Button>
          </div>
          {problems[0] && <p role="alert" className="text-sm text-danger">{problems[0]}</p>}
          <Card>
            <CardContent className="space-y-3 pt-5">
              <p className="text-xs text-ink-muted" aria-live="polite">
                {counted} counted, {shown.length} of {sheet.data.items.length} items shown. Leave an item empty if there is none here.{' '}
                {failed ? <span className="font-medium text-danger">Could not save: {failed}. Your numbers are still here, press Save to try again.</span>
                  : dirty.size > 0 ? <span className="font-medium text-warn">{saving ? 'Saving...' : `${dirty.size} change(s) not saved yet.`}</span>
                    : saved ? <span className="font-medium text-ok">All changes saved at {saved}. You can close this page and come back to carry on.</span> : 'Your numbers are saved as you type.'}
              </p>
              <Table>
                <thead>
                  <tr>
                    {showPictures && <Th>Picture</Th>}<Th>Item</Th><Th>Category</Th><Th>Unit</Th>
                    {showBooks && <Th className="text-right">System stock here</Th>}
                    <Th className="text-right" title="What the books hold in all locations">In all</Th>
                    <Th className="text-right" title="Counted so far in the other locations">Counted elsewhere</Th>
                    <Th className="text-right" title="The most that can be entered here">Up to</Th>
                    <Th>Counted here</Th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((i) => {
                    const mine = typed[i.item_id] ?? { qty: '', reason: '' }
                    const total = i.others + Number(mine.qty || 0)
                    const aboveBooks = mine.qty !== '' && total > i.book
                    const note = problems[i.item_id] ?? (aboveBooks ? 'reason' : null)
                    return (
                      <Fragment key={i.item_id}>
                        <tr>
                          {showPictures && <Td><ItemThumb path={i.image_path} name={i.name} className="h-14 w-14" /></Td>}
                          <Td className="font-medium">{i.code} - {i.name}{i.storage_location && <span className="block text-xs font-normal text-ink-muted">{i.storage_location}</span>}</Td>
                          <Td className="text-xs">{i.category}</Td>
                          <Td className="text-xs">{i.unit}</Td>
                          {showBooks && <Td className="text-right font-semibold tabular-nums">{i.here}</Td>}
                          <Td className="text-right tabular-nums">{i.book}</Td>
                          <Td className="text-right tabular-nums">{i.others}</Td>
                          <Td className="text-right tabular-nums">{i.allowance}</Td>
                          <Td><Input aria-label={`Counted ${i.name}`} type="number" min={0} inputMode="numeric" className="w-28" disabled={finished} value={mine.qty}
                            onChange={(e) => change(i.item_id, { qty: e.target.value })} onBlur={() => void persist()} /></Td>
                        </tr>
                        {note && (
                          <tr>
                            <Td colSpan={7 + (showBooks ? 1 : 0) + (showPictures ? 1 : 0)} className="bg-surface-muted/40">
                              {problems[i.item_id] ? <p role="alert" className="text-xs font-medium text-danger">{problems[i.item_id]}</p> : (
                                <div className="flex flex-wrap items-center gap-2">
                                  <p className="text-xs text-warn">Together that is more than the {i.book} the books hold. Say why:</p>
                                  <Input aria-label={`Reason for ${i.name}`} className="max-w-sm" maxLength={500} disabled={finished} value={mine.reason} onChange={(e) => change(i.item_id, { reason: e.target.value })} />
                                </div>
                              )}
                            </Td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </Table>
              <div className="flex flex-wrap gap-2 pt-2">
                {finished && sheet.data.round_status === 'counting'
                  ? <Button variant="outline" onClick={reopen}>Reopen this count</Button>
                  : !finished && (
                    <>
                      <Button variant="outline" disabled={dirty.size === 0 || saving} onClick={() => void persist()}>Save</Button>
                      <Button disabled={dirty.size > 0 || saving} onClick={finish}>Mark {locationName} as counted</Button>
                    </>
                  )}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
