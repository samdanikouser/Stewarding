import { Download, FileText, Printer } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { api } from '@/lib/api'
import { downloadFile, fetchText, openPdf } from '@/lib/download'
import { useRun, useToast } from '@/lib/toast'
import { useApi } from '@/lib/useApi'
import { findLocalZebra, printOnLocalZebra, type LocalHelper } from '@/lib/zebraLocal'

interface NetworkPrinter {
  id: number
  name: string
  dpi: number
}

const CHOICE = 'lot_label_printer'

// the Zebra helper on this computer is looked for once per page load, not each time a label panel opens
let helperSearch: Promise<LocalHelper | null> | undefined

/** Prints the 75 x 50 mm labels for some lots: straight to a network Zebra, to a Zebra on this computer, or as a PDF or ZPL file. */
export function LabelActions({ ids, copies: start = 1, packs = 0 }: { ids: number[]; copies?: number; packs?: number }) {
  const toast = useToast()
  const run = useRun()
  const printers = useApi<NetworkPrinter[]>('/label-printers').data ?? []
  const [local, setLocal] = useState<LocalHelper | null>(null)
  const [copies, setCopies] = useState(String(start))
  const [dpi, setDpi] = useState('203')
  const [style, setStyle] = useState<'container' | 'pack'>('container')
  const [chosen, setChosen] = useState<string>(() => {
    try {
      return localStorage.getItem(CHOICE) ?? ''
    } catch {
      return ''
    }
  })
  const count = Math.min(50, Math.max(1, Number(copies) || 1))
  const query = `ids=${ids.join(',')}&copies=${count}&style=${style}`
  const printer = printers.find((p) => String(p.id) === chosen) ?? printers[0]

  useEffect(() => {
    let live = true
    helperSearch ??= findLocalZebra()
    helperSearch.then((found) => live && setLocal(found))
    return () => {
      live = false
    }
  }, [])

  function choose(id: string) {
    setChosen(id)
    try {
      localStorage.setItem(CHOICE, id)
    } catch {
      /* the choice is only a convenience */
    }
  }

  const toNetwork = () => run(() => api('/label-printers/print', { body: { printer_id: printer.id, lot_ids: ids, copies: count, style } }), `Sent to ${printer?.name}`)

  async function onThisComputer() {
    if (!local) return
    try {
      await printOnLocalZebra(local, await fetchText(`/api/lots/labels?${query}&fmt=zpl&dpi=${dpi}`))
      toast('ok', `Sent to ${local.printer.name}`)
    } catch (err) {
      toast('error', err instanceof Error ? err.message : 'Could not print')
    }
  }

  async function pdf() {
    if (!(await openPdf(`/api/lots/labels?${query}`))) toast('error', 'Could not make the labels')
  }

  async function zplFile() {
    if (!(await downloadFile(`/api/lots/labels?${query}&fmt=zpl&dpi=${dpi}`, 'lot-labels.zpl'))) toast('error', 'Could not make the Zebra file')
  }

  const first = printer ? 'network' : local ? 'local' : 'pdf'
  return (
    <div className="space-y-2">
      {packs > 0 && (
        <div className="space-y-1">
          <div role="group" aria-label="Label type" className="inline-flex flex-wrap rounded-lg border border-border bg-surface p-0.5">
            {([['container', 'One label for the container'], ['pack', `A label for each pack (${packs})`]] as const).map(([key, text]) => (
              <button key={key} type="button" aria-pressed={style === key} onClick={() => setStyle(key)}
                className={`min-h-9 rounded-md px-3 text-sm font-medium ${style === key ? 'bg-brand text-brand-ink' : 'text-ink-muted hover:text-ink'}`}>{text}</button>
            ))}
          </div>
          {style === 'pack' && <p className="text-xs text-ink-muted">{packs * count} label{packs * count === 1 ? '' : 's'} will print, each with the weight of one pack and the lot code.</p>}
        </div>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <label className="w-full text-xs text-ink-muted sm:w-auto">
          Copies of each
          <Input aria-label="Copies of each label" type="number" min={1} max={50} className="mt-1 h-9 w-20" value={copies} onChange={(e) => setCopies(e.target.value)} />
        </label>
        {printers.length > 1 && (
          <Select aria-label="Label printer" className="h-9 w-auto" value={String(printer?.id ?? '')} onChange={(e) => choose(e.target.value)}>
            {printers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        )}
        {printer && <Button type="button" className="w-full sm:w-auto" onClick={toNetwork}><Printer className="h-4 w-4" aria-hidden /> Print to {printer.name}</Button>}
        {local && <Button type="button" className="w-full sm:w-auto" variant={first === 'local' ? 'default' : 'outline'} onClick={onThisComputer}><Printer className="h-4 w-4" aria-hidden /> Print on this computer&apos;s Zebra</Button>}
        <Button type="button" className="w-full sm:w-auto" variant={first === 'pdf' ? 'default' : 'outline'} onClick={pdf}><FileText className="h-4 w-4" aria-hidden /> Labels as PDF</Button>
        <Button type="button" className="w-full sm:w-auto" variant="outline" onClick={zplFile}><Download className="h-4 w-4" aria-hidden /> Zebra file (ZPL)</Button>
        {!printer && (
          <Select aria-label="Printer resolution" className="h-9 w-auto" value={dpi} onChange={(e) => setDpi(e.target.value)}>
            <option value="203">203 dpi</option>
            <option value="300">300 dpi</option>
          </Select>
        )}
      </div>
    </div>
  )
}
