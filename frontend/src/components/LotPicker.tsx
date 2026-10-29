import { QrCode, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { LotScanner } from '@/components/LotScanner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { fmtDateTime } from '@/lib/format'

export interface LotChoice {
  id: number
  code: string
  label?: string
}

interface Suggestion extends LotChoice {
  item: string
  use_by: string | null
  past_use_by: boolean
  condition_label: string
  location: string
  pack: string | null
  supplier_lot: string | null
}

interface Props {
  value: LotChoice[]
  onChange: (lots: LotChoice[]) => void
  /** How many lots may be chosen; one replaces the choice, more adds to it. */
  max?: number
  /** A typed name used instead of a lot, for food that was not received as one; choosing a lot or a name clears the other. */
  allowCustom?: { value: string; onChange: (text: string) => void }
}

/** Choose food lots by typing a code or a name, or by scanning the QR on the label; lots that may not be used are refused. */
export function LotPicker({ value, onChange, max = 20, allowCustom }: Props) {
  const [text, setText] = useState('')
  const [found, setFound] = useState<Suggestion[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)

  useEffect(() => {
    const typed = text.trim()
    if (!typed) return
    const timer = setTimeout(() => {
      api<Suggestion[]>(`/lots/search?q=${encodeURIComponent(typed)}`).then(setFound).catch(() => setFound([]))
    }, 200)
    return () => clearTimeout(timer)
  }, [text])

  function add(lot: LotChoice) {
    setProblem(null)
    setText('')
    setFound([])
    allowCustom?.onChange('')
    if (value.some((v) => v.id === lot.id)) return
    onChange(max === 1 ? [lot] : [...value, lot].slice(0, max))
  }

  function keepTyped(name: string) {
    setProblem(null)
    setText('')
    setFound([])
    onChange([])
    allowCustom?.onChange(name.trim().slice(0, 120))
  }

  async function addByCode(code: string) {
    if (!code.trim()) return
    try {
      const lot = await api<LotChoice & { blocked: string | null; item?: string; pack_description?: string | null }>(`/lots/by-code/${encodeURIComponent(code.trim())}`)
      if (lot.blocked) setProblem(lot.blocked)
      else add({ id: lot.id, code: lot.code, label: [lot.item, lot.pack_description].filter(Boolean).join(' - ') || undefined })
    } catch (err) {
      if (allowCustom) keepTyped(code)
      else setProblem(err instanceof Error ? err.message : 'Could not find that lot')
    }
  }

  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Chosen lots">
          {value.map((lot) => (
            <li key={lot.id} className="flex items-center gap-1 rounded-full bg-brand-soft py-1 pl-3 pr-1 text-sm font-medium text-brand">
              {lot.label ? `${lot.label} (${lot.code})` : lot.code}
              <button type="button" aria-label={`Remove ${lot.code}`} className="rounded-full p-1 hover:bg-surface/60" onClick={() => onChange(value.filter((v) => v.id !== lot.id))}>
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      {allowCustom?.value && (
        <ul className="flex flex-wrap gap-2" aria-label="Typed name">
          <li className="flex items-center gap-1 rounded-full bg-surface-muted py-1 pl-3 pr-1 text-sm font-medium">
            {allowCustom.value}
            <button type="button" aria-label={`Remove ${allowCustom.value}`} className="rounded-full p-1 hover:bg-surface/60" onClick={() => allowCustom.onChange('')}>
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </li>
        </ul>
      )}
      {(max !== 1 || value.length === 0) && (
        <div className="flex gap-2">
          <Input
            aria-label="Lot code or food name"
            placeholder={allowCustom ? 'Type a food name, portion name or lot code' : 'Type a lot code, food name or portion name'}
            value={text}
            onChange={(e) => { setText(e.target.value); setProblem(null); if (!e.target.value.trim()) setFound([]) }}
            onKeyDown={(e) => {
              if (e.key !== 'Enter') return
              e.preventDefault()
              if (found.length === 1) add(found[0])
              else void addByCode(text)
            }}
          />
          <Button type="button" variant="outline" onClick={() => setScanning(true)}><QrCode className="h-4 w-4" aria-hidden /> Scan</Button>
        </div>
      )}
      {problem && <p role="alert" className="text-sm text-danger">{problem}</p>}
      {!problem && text.trim().length >= 3 && found.length === 0 && !allowCustom && <p className="text-xs text-ink-muted">No lot to choose from matches. Press Enter to check this exact code.</p>}
      {!problem && text.trim().length >= 3 && found.length === 0 && allowCustom && <p className="text-xs text-ink-muted">No lot matches. Press Enter to use what you typed.</p>}
      {text.trim() !== '' && found.length > 0 && (
        <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-lg border border-border bg-surface">
          {found.map((lot) => (
            <li key={lot.id}>
              <button
                type="button"
                disabled={lot.past_use_by}
                className="flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-surface-muted disabled:opacity-50"
                onClick={() => add({ id: lot.id, code: lot.code, label: [lot.item, lot.pack].filter(Boolean).join(' - ') })}
              >
                <span><span className="font-medium">{lot.code}</span> <span className="text-ink-muted">{lot.item}{lot.pack ? `, ${lot.pack}` : ''}{lot.supplier_lot && lot.supplier_lot !== lot.code ? `, supplier batch ${lot.supplier_lot}` : ''}</span></span>
                {lot.past_use_by ? <Badge tone="critical">Past use-by</Badge> : <span className="text-xs text-ink-muted">Use by {fmtDateTime(lot.use_by)}</span>}
              </button>
            </li>
          ))}
          {allowCustom && text.trim().length >= 2 && (
            <li>
              <button type="button" className="w-full px-3 py-2 text-left text-sm font-medium text-brand-deep hover:bg-surface-muted" onClick={() => keepTyped(text)}>
                Use &quot;{text.trim()}&quot; as typed
              </button>
            </li>
          )}
        </ul>
      )}
      <LotScanner open={scanning} onClose={() => setScanning(false)} onScan={(code) => { setScanning(false); void addByCode(code) }} />
    </div>
  )
}
